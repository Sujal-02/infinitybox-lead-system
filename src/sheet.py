import gspread
from pydantic import BaseModel

from .cfg import env
from .models import Account, Draft, Lead, LeadRow, Person, Score, Signal, Source

TABS: dict[str, type[BaseModel]] = {
    "Accounts": Account, "Signals": Signal, "People": Person,
    "Scores": Score, "Drafts": Draft, "Leads": Lead, "Sources": Source, "Pipeline": LeadRow,
}


def columns(tab: str) -> list[str]:
    return list(TABS[tab].model_fields)


def open_book():
    gc = gspread.service_account(filename=env("GOOGLE_CREDS_PATH", "creds.json"))
    return gc.open_by_key(env("GSHEET_ID"))


def init(book) -> list[str]:
    """Create any missing tabs with header rows. Returns the tabs created."""
    have = {w.title for w in book.worksheets()}
    made = []
    for tab in TABS:
        if tab not in have:
            book.add_worksheet(title=tab, rows=1000, cols=len(columns(tab)))
            made.append(tab)
        ws = book.worksheet(tab)
        if not ws.row_values(1):
            ws.append_row(columns(tab))
    return made


def _row(tab: str, m: BaseModel) -> list:
    d = m.model_dump(mode="json")
    return ["" if d[c] is None else d[c] for c in columns(tab)]


def append(book, tab: str, rows: list[BaseModel]) -> None:
    if rows:
        book.worksheet(tab).append_rows([_row(tab, r) for r in rows])


def read(book, tab: str) -> list[BaseModel]:
    recs = book.worksheet(tab).get_all_records()
    return [TABS[tab].model_validate({k: v for k, v in r.items() if v != ""}) for r in recs]


def replace(book, tab: str, rows: list[BaseModel]) -> None:
    """Overwrite a tab's data (used for Scores, which is recomputed each run)."""
    ws = book.worksheet(tab)
    ws.clear()
    ws.append_rows([columns(tab)] + [_row(tab, r) for r in rows])


def export_xlsx(path, tables: dict[str, list[BaseModel]]) -> None:
    """Local alternative to Google Sheets: one tab per table, header row, filters, frozen header. No credentials needed.
    Open in Excel, or drag into Google Drive / import into a Google Sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    wb.remove(wb.active)
    for tab, rows in tables.items():
        ws = wb.create_sheet(tab)
        cols = columns(tab)
        ws.append(cols)
        for r in rows:
            ws.append(_row(tab, r))
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = ws.dimensions
        for i, col in enumerate(cols, 1):
            width = min(max([len(str(col))] + [len(str(v)) for v in (ws.cell(row=j, column=i).value for j in range(2, min(ws.max_row, 60) + 1))]) + 2, 60)
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
            for j in range(2, ws.max_row + 1):
                ws.cell(row=j, column=i).alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)
