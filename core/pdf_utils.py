import os
from pathlib import Path
from threading import Lock

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Image, Paragraph
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle


_FONT_LOCK = Lock()
_FONT_CACHE = None
_FONT_ALIAS_REGULAR = "AssistenciaSans"
_FONT_ALIAS_BOLD = "AssistenciaSans-Bold"


def _font_pairs_candidates():
    custom_regular = os.getenv("ASSISTENCIA_PDF_FONT_REGULAR", "").strip()
    custom_bold = os.getenv("ASSISTENCIA_PDF_FONT_BOLD", "").strip()
    if custom_regular and custom_bold:
        yield custom_regular, custom_bold

    project_root = Path(__file__).resolve().parent.parent
    yield (
        str(project_root / "core" / "static" / "fonts" / "DejaVuSans.ttf"),
        str(project_root / "core" / "static" / "fonts" / "DejaVuSans-Bold.ttf"),
    )

    yield ("C:\\Windows\\Fonts\\DejaVuSans.ttf", "C:\\Windows\\Fonts\\DejaVuSans-Bold.ttf")
    yield ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf")
    yield ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    yield ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf")


def get_pdf_fonts():
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE

    with _FONT_LOCK:
        if _FONT_CACHE:
            return _FONT_CACHE

        registered = set(pdfmetrics.getRegisteredFontNames())
        if _FONT_ALIAS_REGULAR in registered and _FONT_ALIAS_BOLD in registered:
            _FONT_CACHE = {"regular": _FONT_ALIAS_REGULAR, "bold": _FONT_ALIAS_BOLD}
            return _FONT_CACHE

        for regular_path, bold_path in _font_pairs_candidates():
            if not (os.path.exists(regular_path) and os.path.exists(bold_path)):
                continue
            try:
                if _FONT_ALIAS_REGULAR not in registered:
                    pdfmetrics.registerFont(TTFont(_FONT_ALIAS_REGULAR, regular_path))
                if _FONT_ALIAS_BOLD not in registered:
                    pdfmetrics.registerFont(TTFont(_FONT_ALIAS_BOLD, bold_path))
                _FONT_CACHE = {"regular": _FONT_ALIAS_REGULAR, "bold": _FONT_ALIAS_BOLD}
                return _FONT_CACHE
            except Exception:
                continue

        _FONT_CACHE = {"regular": "Helvetica", "bold": "Helvetica-Bold"}
        return _FONT_CACHE


def add_paragraph_styles(stylesheet, fonts, specs):
    for name, cfg in specs.items():
        font_name = fonts["bold"] if cfg.get("bold") else fonts["regular"]
        kwargs = {
            "name": name,
            "fontName": font_name,
            "fontSize": cfg["font_size"],
            "leading": cfg["leading"],
            # Evita sobreposição horizontal quando há tokens longos (e-mail, código, URL etc.).
            "splitLongWords": int(bool(cfg.get("split_long_words", True))),
        }
        if "text_color" in cfg:
            kwargs["textColor"] = cfg["text_color"]
        if "alignment" in cfg:
            kwargs["alignment"] = cfg["alignment"]
        if "word_wrap" in cfg:
            kwargs["wordWrap"] = cfg["word_wrap"]
        if "allow_widows" in cfg:
            kwargs["allowWidows"] = int(bool(cfg["allow_widows"]))
        if "allow_orphans" in cfg:
            kwargs["allowOrphans"] = int(bool(cfg["allow_orphans"]))
        stylesheet.add(ParagraphStyle(**kwargs))


def make_numbered_canvas(footer_callback):
    class NumberedCanvas(pdf_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                footer_callback(self, total_pages)
                pdf_canvas.Canvas.showPage(self)
            pdf_canvas.Canvas.save(self)

    return NumberedCanvas


def resolve_logo_path(empresa, field_name="logo_pdf"):
    if empresa and getattr(empresa, field_name, None):
        try:
            campo = getattr(empresa, field_name)
            if campo.name and os.path.exists(campo.path):
                return campo.path
        except Exception:
            return None
    return None


def logo_or_paragraph(empresa, style, fallback, width, height, field_name="logo_pdf", align="CENTER"):
    logo_path = resolve_logo_path(empresa, field_name=field_name)
    if logo_path:
        try:
            try:
                img_reader = ImageReader(logo_path)
                img_width, img_height = img_reader.getSize()
                scale = min(width / float(img_width or 1), height / float(img_height or 1))
                render_width = max(0.1 * cm, img_width * scale)
                render_height = max(0.1 * cm, img_height * scale)
            except Exception:
                render_width = width
                render_height = height
            logo = Image(logo_path, width=render_width, height=render_height)
            if hasattr(logo, "hAlign"):
                logo.hAlign = align
            return logo
        except Exception:
            pass

    fallback_text = fallback
    if empresa and getattr(empresa, "nome", ""):
        fallback_text = f"<b>{empresa.nome}</b>"
    return Paragraph(fallback_text, style)


__all__ = [
    "add_paragraph_styles",
    "get_pdf_fonts",
    "logo_or_paragraph",
    "make_numbered_canvas",
    "resolve_logo_path",
]
