from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


# =========================================
# Base Schema
# =========================================

class BaseArtifactSchema(BaseModel):
    version: str = "1.0"
    file_name: str


# =========================================
# PowerPoint Schemas
# =========================================

class Bullet(BaseModel):
    text: str
    level: int = 0


class ChartData(BaseModel):
    chart_type: Literal["line", "bar"]
    categories: List[str]
    series: Dict[str, List[float]]
    title: Optional[str] = None
    position: Optional[tuple] = (1, 2)  # inches (x, y)
    size: Optional[tuple] = (6, 4)      # inches (width, height)


class TableSlideData(BaseModel):
    headers: List[str]
    rows: List[List[str]]


class Slide(BaseModel):
    title: Optional[str] = None
    bullets: List[Bullet] = Field(default_factory=list)
    layout: Literal["title", "content", "blank"] = "content"

    image_path: Optional[str] = None
    background_image: Optional[str] = None

    notes: Optional[str] = None

    chart: Optional[ChartData] = None
    table: Optional[TableSlideData] = None


class PresentationSchema(BaseArtifactSchema):
    slides: List[Slide]
    footer_text: Optional[str] = None


    
# ==============================
# Excel Schemas
# ==============================

class ColumnFormat(BaseModel):
    column: str
    number_format: Optional[str] = None
    width: Optional[int] = None
    alignment: Optional[Literal["left", "center", "right"]] = None


class ConditionalFormat(BaseModel):
    column: str
    type: Literal["greater_than", "less_than"]
    value: float


class ChartConfig(BaseModel):
    chart_type: Literal["line", "bar"]
    x_column: str
    y_columns: List[str]
    title: Optional[str] = None
    position: Optional[str] = "A10"
    width: Optional[int] = 15
    height: Optional[int] = 10


class SheetData(BaseModel):
    name: str
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    charts: List[ChartConfig] = Field(default_factory=list)
    formula_columns: List[str] = Field(default_factory=list)
    column_formats: List[ColumnFormat] = Field(default_factory=list)
    conditional_formats: List[ConditionalFormat] = Field(default_factory=list)
    auto_filter: bool = True


class ExcelSchema(BaseArtifactSchema):
    sheets: List[SheetData]

# =========================================
# Word Schemas
# =========================================

class Paragraph(BaseModel):
    text: str
    style: Optional[str] = None
    heading_level: Optional[int] = None
    bold: bool = False
    italic: bool = False
    alignment: Optional[Literal["left", "center", "right"]] = None
    list_type: Optional[Literal["bullet", "numbered"]] = None
    page_break_before: bool = False


class ImageData(BaseModel):
    path: str
    width: Optional[float] = None  # Inches


class TableData(BaseModel):
    headers: List[str]
    rows: List[List[str]] = Field(default_factory=list)
    style: Optional[str] = "Table Grid"


class WordSchema(BaseArtifactSchema):
    paragraphs: List[Paragraph] = Field(default_factory=list)
    tables: List[TableData] = Field(default_factory=list)
    images: List[ImageData] = Field(default_factory=list)
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
