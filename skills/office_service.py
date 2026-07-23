"""
Office service - unified win32com control for Word, Excel and PowerPoint.

Primary method is COM automation (not mouse/keyboard). Word live-typing
inserts section-by-section through COM so the user watches the document
build. COM is only initialized on the calling thread (pythoncom.CoInitialize)
so it is safe to use from worker threads.
"""
import queue
import threading


def _com(progid):
    import pythoncom
    import win32com.client
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    # Every JARVIS Office task owns an isolated application instance.  Attaching
    # to a user's existing Word/Excel/PowerPoint session makes cancellation and
    # shutdown unsafe and can block while an unrelated document is interactive.
    return win32com.client.DispatchEx(progid)


def _word_com():
    """Acquire Word without starting a second instance behind a template lock.

    Word can leave an otherwise empty application running.  DispatchEx then
    starts a hidden second process which may block on Normal.dotm.  Reuse the
    responsive running automation server when available, but track ownership
    so JARVIS closes only the document it created and never quits a user's
    Word application.
    """
    import pythoncom
    import win32com.client
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass
    try:
        return win32com.client.GetActiveObject("Word.Application"), False
    except Exception:
        return win32com.client.DispatchEx("Word.Application"), True


# ===========================================================================
# WORD
# ===========================================================================
class WordService:
    def __init__(self):
        self.app = None
        self.window_handle = None
        self.process_id = None
        self._document = None
        self._commands = queue.Queue()
        self._worker = None
        self._ready = threading.Event()
        self._owns_application = False

    def _start_worker(self):
        if self._worker is not None and self._worker.is_alive():
            return

        def run():
            import pythoncom
            pythoncom.CoInitialize()
            self._ready.set()
            try:
                while True:
                    command = self._commands.get()
                    if command is None:
                        break
                    function, args, done, outcome = command
                    try:
                        outcome["result"] = function(*args)
                    except Exception as exc:
                        outcome["error"] = exc
                    finally:
                        done.set()
            finally:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

        self._ready.clear()
        self._worker = threading.Thread(
            target=run, name="JARVIS-Word-COM", daemon=True
        )
        self._worker.start()
        if not self._ready.wait(timeout=5):
            raise TimeoutError("Word COM worker did not start")

    def _call(self, function, *args):
        self._start_worker()
        if threading.current_thread() is self._worker:
            return function(*args)
        done = threading.Event()
        outcome = {}
        self._commands.put((function, args, done, outcome))
        if not done.wait(timeout=120):
            raise TimeoutError("Word COM operation timed out")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("result")

    def open(self, visible=True):
        def operation():
            self.app, self._owns_application = _word_com()
            self.app.Visible = visible
            try:
                self.window_handle = int(self.app.Hwnd)
                import ctypes
                process_id = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(
                    self.window_handle, ctypes.byref(process_id)
                )
                self.process_id = int(process_id.value) or None
            except Exception:
                self.window_handle = None
                self.process_id = None
            return True

        return self._call(operation)

    def _ensure(self):
        if self.app is None:
            self.open()
        return self.app

    def new_document(self):
        def operation():
            self._document = self._ensure().Documents.Add()
            return "active_document"

        return self._call(operation)

    def open_document(self, path):
        def operation():
            self._document = self._ensure().Documents.Open(str(path))
            return "active_document"

        return self._call(operation)

    def insert_heading(self, text, level=1, doc=None):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            text_range = document.Content
            text_range.Collapse(0)
            style = document.Styles(f"Heading {level}")
            text_range.InsertAfter(str(text) + "\r")
            text_range.Style = style
            return True

        return self._call(operation)

    def insert_paragraph(self, text, doc=None):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            text_range = document.Content
            text_range.Collapse(0)
            text_range.InsertAfter(str(text) + "\r")
            return True

        return self._call(operation)

    def insert_text(self, text, doc=None):
        return self.insert_paragraph(text, doc=doc)

    def apply_heading(self, text, level=1, doc=None):
        return self.insert_heading(text, level=level, doc=doc)

    def apply_paragraph_style(self, style_name="Normal", doc=None):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            paragraph = document.Paragraphs(document.Paragraphs.Count)
            paragraph.Range.Style = document.Styles(str(style_name))
            return True

        return self._call(operation)

    def insert_table(self, rows, columns=None, data=None, doc=None):
        values = list(data) if data is not None else []
        row_count = len(values) if data is not None else int(rows)
        column_count = int(columns or (max((len(row) for row in values), default=1)))

        def operation():
            document = self._document or self._ensure().ActiveDocument
            text_range = document.Content
            text_range.Collapse(0)
            table = document.Tables.Add(text_range, row_count, column_count)
            for row_index, row in enumerate(values[:row_count], 1):
                for column_index, value in enumerate(list(row)[:column_count], 1):
                    table.Cell(row_index, column_index).Range.Text = str(value)
            return table

        return self._call(operation)

    def insert_page_break(self, doc=None):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            text_range = document.Content
            text_range.Collapse(0)
            text_range.InsertBreak(7)
            return True

        return self._call(operation)

    def add_page_numbers(self, doc=None):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            for section in document.Sections:
                section.Footers(1).PageNumbers.Add()
            return True

        return self._call(operation)

    def insert_bullets(self, items, doc=None):
        for item in items:
            self.insert_paragraph("• " + str(item), doc=doc)
        return True

    def type_visibly(self, text, doc=None):
        """Insert a paragraph through COM (reliable live typing)."""
        return self.insert_paragraph(text, doc=doc)

    def save(self, path=None, doc=None):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            if path:
                try:
                    document.SaveAs2(str(path))
                except AttributeError:
                    document.SaveAs(str(path))
                return str(path)
            document.Save()
            try:
                return document.FullName
            except Exception:
                return ""

        return self._call(operation)

    def export_pdf(self, path, doc=None):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            document.ExportAsFixedFormat(str(path), 17)
            return str(path)

        return self._call(operation)

    def read_text(self, doc=None):
        return self._call(
            lambda: (self._document or self._ensure().ActiveDocument).Content.Text
        )

    def close_document(self, save=True):
        def operation():
            document = self._document or self._ensure().ActiveDocument
            document.Close(SaveChanges=-1 if save else 0)
            self._document = None
            return True

        return self._call(operation)

    def close(self, save=False):
        if self._worker is None:
            return False

        def operation():
            if self.app is None:
                return True
            try:
                document = self._document
                if document is not None:
                    try:
                        document.Close(SaveChanges=-1 if save else 0)
                    except Exception:
                        pass
                if self._owns_application:
                    self.app.Quit()
            finally:
                self._document = None
                self.app = None
                self._owns_application = False
            return True

        try:
            result = self._call(operation)
        finally:
            self._commands.put(None)
            if self._worker is not threading.current_thread():
                try:
                    self._worker.join(timeout=5)
                except Exception:
                    pass
            self._worker = None
        return result


# ===========================================================================
# EXCEL
# ===========================================================================
class ExcelService:
    def __init__(self):
        self.app = None
        self._workbook = None

    def open(self, visible=True):
        self.app = _com("Excel.Application")
        self.app.Visible = visible
        return self.app

    def _ensure(self):
        if self.app is None:
            self.open()
        return self.app

    def new_workbook(self):
        self._workbook = self._ensure().Workbooks.Add()
        return self._workbook

    def _active_workbook(self):
        return self._workbook or self._ensure().ActiveWorkbook

    def select_sheet(self, name):
        sheet = self._active_workbook().Worksheets(str(name))
        sheet.Activate()
        return sheet

    def rename_sheet(self, current_name, new_name):
        sheet = self._active_workbook().Worksheets(str(current_name))
        sheet.Name = str(new_name)[:31]
        return sheet

    def set_cell(self, row, col, value, sheet=None):
        wb = self._active_workbook()
        ws = sheet or wb.ActiveSheet
        ws.Cells(row, col).Value = value
        return True

    def enter_data(self, rows, start_row=1, start_col=1):
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                self.set_cell(start_row + r, start_col + c, value)
        return True

    def write_range(self, rows, start_row=1, start_col=1, sheet=None):
        values = [list(row) for row in rows]
        if not values:
            return True
        worksheet = sheet or self._active_workbook().ActiveSheet
        end_row = start_row + len(values) - 1
        end_col = start_col + max(len(row) for row in values) - 1
        normalized = [row + [None] * (end_col - start_col + 1 - len(row)) for row in values]
        worksheet.Range(
            worksheet.Cells(start_row, start_col), worksheet.Cells(end_row, end_col)
        ).Value = tuple(tuple(row) for row in normalized)
        return True

    def add_formula(self, cell, formula, sheet=None):
        worksheet = sheet or self._active_workbook().ActiveSheet
        worksheet.Range(str(cell)).Formula = str(formula)
        return True

    def format_range(self, address, *, bold=None, number_format=None,
                     autofit=False, sheet=None):
        worksheet = sheet or self._active_workbook().ActiveSheet
        target = worksheet.Range(str(address))
        if bold is not None:
            target.Font.Bold = bool(bold)
        if number_format:
            target.NumberFormat = str(number_format)
        if autofit:
            target.Columns.AutoFit()
        return True

    def create_table(self, address, name="JarvisTable", sheet=None):
        worksheet = sheet or self._active_workbook().ActiveSheet
        source = worksheet.Range(str(address))
        table = worksheet.ListObjects.Add(1, source, None, 1)
        table.Name = str(name)
        return table

    def create_chart(self, address, chart_type=51, sheet=None):
        worksheet = sheet or self._active_workbook().ActiveSheet
        chart = worksheet.Shapes.AddChart2(201, int(chart_type)).Chart
        chart.SetSourceData(worksheet.Range(str(address)))
        return chart

    def save(self, path=None):
        wb = self._active_workbook()
        if path:
            wb.SaveAs(str(path))
            return str(path)
        wb.Save()
        return ""

    def export_csv(self, path, sheet=None):
        worksheet = sheet or self._active_workbook().ActiveSheet
        worksheet.Copy()
        csv_book = self._ensure().ActiveWorkbook
        try:
            csv_book.SaveAs(str(path), FileFormat=6)
        finally:
            csv_book.Close(SaveChanges=False)
        return str(path)

    def close_workbook(self, save=True):
        workbook = self._active_workbook()
        workbook.Close(SaveChanges=bool(save))
        self._workbook = None
        return True

    def close(self, save=False):
        if self.app is None:
            return
        try:
            self.app.DisplayAlerts = False
            self.app.Quit()
        except Exception:
            pass
        self.app = None
        self._workbook = None


# ===========================================================================
# POWERPOINT
# ===========================================================================
class PowerPointService:
    def __init__(self):
        self.app = None
        self._presentation = None

    def open(self, visible=True):
        self.app = _com("PowerPoint.Application")
        try:
            self.app.Visible = visible
        except Exception:
            pass
        return self.app

    def _ensure(self):
        if self.app is None:
            self.open()
        return self.app

    def new_presentation(self):
        self._presentation = self._ensure().Presentations.Add()
        return self._presentation

    def _active_presentation(self):
        return self._presentation or self._ensure().ActivePresentation

    def add_title_slide(self, title, subtitle="", pres=None):
        pres = pres or self._active_presentation()
        slide = pres.Slides.Add(pres.Slides.Count + 1, 1)  # ppLayoutTitle
        slide.Shapes(1).TextFrame.TextRange.Text = str(title)
        if subtitle and slide.Shapes.Count > 1:
            slide.Shapes(2).TextFrame.TextRange.Text = str(subtitle)
        return slide

    def add_bullet_slide(self, title, bullets, pres=None):
        pres = pres or self._active_presentation()
        slide = pres.Slides.Add(pres.Slides.Count + 1, 2)  # ppLayoutText
        slide.Shapes(1).TextFrame.TextRange.Text = str(title)
        body = slide.Shapes(2).TextFrame.TextRange
        body.Text = "\r".join(str(b) for b in bullets)
        return slide

    def save(self, path=None, pres=None):
        pres = pres or self._active_presentation()
        if path:
            pres.SaveAs(str(path))
            return str(path)
        pres.Save()
        return ""

    def add_slide(self, title, body=(), layout=2, pres=None):
        if int(layout) == 1:
            return self.add_title_slide(title, "\n".join(body) if isinstance(body, (list, tuple)) else body, pres)
        bullets = body if isinstance(body, (list, tuple)) else [body]
        return self.add_bullet_slide(title, bullets, pres)

    def add_image(self, path, left=40, top=80, width=-1, height=-1, slide=None):
        slide = slide or self._active_presentation().Slides(self._active_presentation().Slides.Count)
        return slide.Shapes.AddPicture(str(path), False, True, left, top, width, height)

    def add_notes(self, text, slide=None):
        slide = slide or self._active_presentation().Slides(self._active_presentation().Slides.Count)
        slide.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = str(text)
        return True

    def run_slideshow(self, pres=None):
        presentation = pres or self._active_presentation()
        return presentation.SlideShowSettings.Run()

    def export_pdf(self, path, pres=None):
        presentation = pres or self._active_presentation()
        presentation.SaveAs(str(path), 32)
        return str(path)

    def close_presentation(self):
        presentation = self._active_presentation()
        presentation.Close()
        self._presentation = None
        return True

    def close(self):
        if self.app is None:
            return
        try:
            self.app.Quit()
        except Exception:
            pass
        self.app = None
        self._presentation = None
