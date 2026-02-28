# Office Skills Pack Schemas

Generated from live Pydantic models.

## chart

### Schema
```json
{
  "$defs": {
    "SeriesSpec": {
      "properties": {
        "name": {
          "minLength": 1,
          "title": "Name",
          "type": "string"
        },
        "x": {
          "items": {
            "type": "number"
          },
          "minItems": 1,
          "title": "X",
          "type": "array"
        },
        "y": {
          "items": {
            "type": "number"
          },
          "minItems": 1,
          "title": "Y",
          "type": "array"
        }
      },
      "required": [
        "name",
        "x",
        "y"
      ],
      "title": "SeriesSpec",
      "type": "object"
    }
  },
  "properties": {
    "title": {
      "minLength": 1,
      "title": "Title",
      "type": "string"
    },
    "x_label": {
      "default": "",
      "title": "X Label",
      "type": "string"
    },
    "y_label": {
      "default": "",
      "title": "Y Label",
      "type": "string"
    },
    "series": {
      "items": {
        "$ref": "#/$defs/SeriesSpec"
      },
      "minItems": 1,
      "title": "Series",
      "type": "array"
    }
  },
  "required": [
    "title",
    "series"
  ],
  "title": "ChartSpec",
  "type": "object"
}
```

### Minimal example
```json
{
  "title": "Example",
  "x_label": "x",
  "y_label": "y",
  "series": [
    {
      "name": "s1",
      "x": [
        1,
        2,
        3
      ],
      "y": [
        1,
        4,
        9
      ]
    }
  ]
}
```

## excel

### Schema
```json
{
  "$defs": {
    "SheetImageSpec": {
      "properties": {
        "path": {
          "description": "Image path relative to session sandbox",
          "minLength": 1,
          "title": "Path",
          "type": "string"
        },
        "cell": {
          "default": "A1",
          "description": "Top-left anchor cell, e.g. C3",
          "title": "Cell",
          "type": "string"
        },
        "width": {
          "anyOf": [
            {
              "minimum": 1,
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Width"
        },
        "height": {
          "anyOf": [
            {
              "minimum": 1,
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Height"
        }
      },
      "required": [
        "path"
      ],
      "title": "SheetImageSpec",
      "type": "object"
    },
    "SheetSpec": {
      "properties": {
        "name": {
          "minLength": 1,
          "title": "Name",
          "type": "string"
        },
        "columns": {
          "items": {
            "type": "string"
          },
          "minItems": 1,
          "title": "Columns",
          "type": "array"
        },
        "rows": {
          "items": {
            "items": {},
            "type": "array"
          },
          "title": "Rows",
          "type": "array"
        },
        "freeze_panes": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": "A2",
          "title": "Freeze Panes"
        },
        "number_formats": {
          "additionalProperties": {
            "type": "string"
          },
          "title": "Number Formats",
          "type": "object"
        },
        "column_widths": {
          "additionalProperties": {
            "type": "number"
          },
          "title": "Column Widths",
          "type": "object"
        },
        "auto_filter": {
          "default": true,
          "title": "Auto Filter",
          "type": "boolean"
        },
        "header_fill": {
          "default": true,
          "title": "Header Fill",
          "type": "boolean"
        },
        "images": {
          "description": "Images to place in worksheet",
          "items": {
            "$ref": "#/$defs/SheetImageSpec"
          },
          "title": "Images",
          "type": "array"
        }
      },
      "required": [
        "name",
        "columns"
      ],
      "title": "SheetSpec",
      "type": "object"
    }
  },
  "properties": {
    "sheets": {
      "items": {
        "$ref": "#/$defs/SheetSpec"
      },
      "minItems": 1,
      "title": "Sheets",
      "type": "array"
    }
  },
  "required": [
    "sheets"
  ],
  "title": "WorkbookSpec",
  "type": "object"
}
```

### Minimal example
```json
{
  "sheets": [
    {
      "name": "Sheet1",
      "columns": [
        "A",
        "B"
      ],
      "rows": [
        [
          1,
          2
        ],
        [
          3,
          4
        ]
      ]
    }
  ]
}
```

## powerpoint

### Schema
```json
{
  "$defs": {
    "SlideSpec": {
      "properties": {
        "title": {
          "minLength": 1,
          "title": "Title",
          "type": "string"
        },
        "bullets": {
          "items": {
            "type": "string"
          },
          "title": "Bullets",
          "type": "array"
        },
        "image_paths": {
          "description": "Paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Image Paths",
          "type": "array"
        },
        "charts": {
          "description": "Chart PNG paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Charts",
          "type": "array"
        }
      },
      "required": [
        "title"
      ],
      "title": "SlideSpec",
      "type": "object"
    }
  },
  "properties": {
    "title": {
      "minLength": 1,
      "title": "Title",
      "type": "string"
    },
    "slides": {
      "items": {
        "$ref": "#/$defs/SlideSpec"
      },
      "minItems": 1,
      "title": "Slides",
      "type": "array"
    }
  },
  "required": [
    "title",
    "slides"
  ],
  "title": "DeckSpec",
  "type": "object"
}
```

### Minimal example
```json
{
  "title": "Deck",
  "slides": [
    {
      "title": "Slide",
      "bullets": [
        "One"
      ],
      "image_paths": [],
      "charts": []
    }
  ]
}
```

## word

### Schema
```json
{
  "$defs": {
    "SectionSpec": {
      "properties": {
        "heading": {
          "minLength": 1,
          "title": "Heading",
          "type": "string"
        },
        "paragraphs": {
          "items": {
            "type": "string"
          },
          "title": "Paragraphs",
          "type": "array"
        },
        "bullets": {
          "items": {
            "type": "string"
          },
          "title": "Bullets",
          "type": "array"
        },
        "table": {
          "anyOf": [
            {
              "$ref": "#/$defs/TableSpec"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "image_paths": {
          "description": "Image paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Image Paths",
          "type": "array"
        },
        "charts": {
          "description": "Chart PNG paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Charts",
          "type": "array"
        }
      },
      "required": [
        "heading"
      ],
      "title": "SectionSpec",
      "type": "object"
    },
    "TableSpec": {
      "properties": {
        "columns": {
          "items": {
            "type": "string"
          },
          "minItems": 1,
          "title": "Columns",
          "type": "array"
        },
        "rows": {
          "items": {
            "items": {},
            "type": "array"
          },
          "title": "Rows",
          "type": "array"
        }
      },
      "required": [
        "columns"
      ],
      "title": "TableSpec",
      "type": "object"
    }
  },
  "properties": {
    "title": {
      "minLength": 1,
      "title": "Title",
      "type": "string"
    },
    "sections": {
      "items": {
        "$ref": "#/$defs/SectionSpec"
      },
      "minItems": 1,
      "title": "Sections",
      "type": "array"
    }
  },
  "required": [
    "title",
    "sections"
  ],
  "title": "DocSpec",
  "type": "object"
}
```

### Minimal example
```json
{
  "title": "Doc",
  "sections": [
    {
      "heading": "Intro",
      "paragraphs": [
        "Hello"
      ],
      "bullets": []
    }
  ]
}
```

## pack

### Schema
```json
{
  "$defs": {
    "ChartJob": {
      "properties": {
        "path": {
          "description": "PNG output path relative to sandbox",
          "minLength": 1,
          "title": "Path",
          "type": "string"
        },
        "chart": {
          "$ref": "#/$defs/ChartSpec"
        }
      },
      "required": [
        "path",
        "chart"
      ],
      "title": "ChartJob",
      "type": "object"
    },
    "ChartSpec": {
      "properties": {
        "title": {
          "minLength": 1,
          "title": "Title",
          "type": "string"
        },
        "x_label": {
          "default": "",
          "title": "X Label",
          "type": "string"
        },
        "y_label": {
          "default": "",
          "title": "Y Label",
          "type": "string"
        },
        "series": {
          "items": {
            "$ref": "#/$defs/SeriesSpec"
          },
          "minItems": 1,
          "title": "Series",
          "type": "array"
        }
      },
      "required": [
        "title",
        "series"
      ],
      "title": "ChartSpec",
      "type": "object"
    },
    "DeckSpec": {
      "properties": {
        "title": {
          "minLength": 1,
          "title": "Title",
          "type": "string"
        },
        "slides": {
          "items": {
            "$ref": "#/$defs/SlideSpec"
          },
          "minItems": 1,
          "title": "Slides",
          "type": "array"
        }
      },
      "required": [
        "title",
        "slides"
      ],
      "title": "DeckSpec",
      "type": "object"
    },
    "DocSpec": {
      "properties": {
        "title": {
          "minLength": 1,
          "title": "Title",
          "type": "string"
        },
        "sections": {
          "items": {
            "$ref": "#/$defs/SectionSpec"
          },
          "minItems": 1,
          "title": "Sections",
          "type": "array"
        }
      },
      "required": [
        "title",
        "sections"
      ],
      "title": "DocSpec",
      "type": "object"
    },
    "SectionSpec": {
      "properties": {
        "heading": {
          "minLength": 1,
          "title": "Heading",
          "type": "string"
        },
        "paragraphs": {
          "items": {
            "type": "string"
          },
          "title": "Paragraphs",
          "type": "array"
        },
        "bullets": {
          "items": {
            "type": "string"
          },
          "title": "Bullets",
          "type": "array"
        },
        "table": {
          "anyOf": [
            {
              "$ref": "#/$defs/TableSpec"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "image_paths": {
          "description": "Image paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Image Paths",
          "type": "array"
        },
        "charts": {
          "description": "Chart PNG paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Charts",
          "type": "array"
        }
      },
      "required": [
        "heading"
      ],
      "title": "SectionSpec",
      "type": "object"
    },
    "SeriesSpec": {
      "properties": {
        "name": {
          "minLength": 1,
          "title": "Name",
          "type": "string"
        },
        "x": {
          "items": {
            "type": "number"
          },
          "minItems": 1,
          "title": "X",
          "type": "array"
        },
        "y": {
          "items": {
            "type": "number"
          },
          "minItems": 1,
          "title": "Y",
          "type": "array"
        }
      },
      "required": [
        "name",
        "x",
        "y"
      ],
      "title": "SeriesSpec",
      "type": "object"
    },
    "SheetImageSpec": {
      "properties": {
        "path": {
          "description": "Image path relative to session sandbox",
          "minLength": 1,
          "title": "Path",
          "type": "string"
        },
        "cell": {
          "default": "A1",
          "description": "Top-left anchor cell, e.g. C3",
          "title": "Cell",
          "type": "string"
        },
        "width": {
          "anyOf": [
            {
              "minimum": 1,
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Width"
        },
        "height": {
          "anyOf": [
            {
              "minimum": 1,
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Height"
        }
      },
      "required": [
        "path"
      ],
      "title": "SheetImageSpec",
      "type": "object"
    },
    "SheetSpec": {
      "properties": {
        "name": {
          "minLength": 1,
          "title": "Name",
          "type": "string"
        },
        "columns": {
          "items": {
            "type": "string"
          },
          "minItems": 1,
          "title": "Columns",
          "type": "array"
        },
        "rows": {
          "items": {
            "items": {},
            "type": "array"
          },
          "title": "Rows",
          "type": "array"
        },
        "freeze_panes": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": "A2",
          "title": "Freeze Panes"
        },
        "number_formats": {
          "additionalProperties": {
            "type": "string"
          },
          "title": "Number Formats",
          "type": "object"
        },
        "column_widths": {
          "additionalProperties": {
            "type": "number"
          },
          "title": "Column Widths",
          "type": "object"
        },
        "auto_filter": {
          "default": true,
          "title": "Auto Filter",
          "type": "boolean"
        },
        "header_fill": {
          "default": true,
          "title": "Header Fill",
          "type": "boolean"
        },
        "images": {
          "description": "Images to place in worksheet",
          "items": {
            "$ref": "#/$defs/SheetImageSpec"
          },
          "title": "Images",
          "type": "array"
        }
      },
      "required": [
        "name",
        "columns"
      ],
      "title": "SheetSpec",
      "type": "object"
    },
    "SlideSpec": {
      "properties": {
        "title": {
          "minLength": 1,
          "title": "Title",
          "type": "string"
        },
        "bullets": {
          "items": {
            "type": "string"
          },
          "title": "Bullets",
          "type": "array"
        },
        "image_paths": {
          "description": "Paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Image Paths",
          "type": "array"
        },
        "charts": {
          "description": "Chart PNG paths relative to session sandbox",
          "items": {
            "type": "string"
          },
          "title": "Charts",
          "type": "array"
        }
      },
      "required": [
        "title"
      ],
      "title": "SlideSpec",
      "type": "object"
    },
    "TableSpec": {
      "properties": {
        "columns": {
          "items": {
            "type": "string"
          },
          "minItems": 1,
          "title": "Columns",
          "type": "array"
        },
        "rows": {
          "items": {
            "items": {},
            "type": "array"
          },
          "title": "Rows",
          "type": "array"
        }
      },
      "required": [
        "columns"
      ],
      "title": "TableSpec",
      "type": "object"
    },
    "WorkbookSpec": {
      "properties": {
        "sheets": {
          "items": {
            "$ref": "#/$defs/SheetSpec"
          },
          "minItems": 1,
          "title": "Sheets",
          "type": "array"
        }
      },
      "required": [
        "sheets"
      ],
      "title": "WorkbookSpec",
      "type": "object"
    }
  },
  "properties": {
    "strict": {
      "default": true,
      "title": "Strict",
      "type": "boolean"
    },
    "dry_run": {
      "default": false,
      "title": "Dry Run",
      "type": "boolean"
    },
    "charts": {
      "items": {
        "$ref": "#/$defs/ChartJob"
      },
      "title": "Charts",
      "type": "array"
    },
    "xlsx_path": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Xlsx Path"
    },
    "pptx_path": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Pptx Path"
    },
    "docx_path": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Docx Path"
    },
    "workbook": {
      "anyOf": [
        {
          "$ref": "#/$defs/WorkbookSpec"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "deck": {
      "anyOf": [
        {
          "$ref": "#/$defs/DeckSpec"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "doc": {
      "anyOf": [
        {
          "$ref": "#/$defs/DocSpec"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    }
  },
  "title": "PackSpec",
  "type": "object"
}
```

### Minimal example
```json
{
  "strict": true,
  "charts": [],
  "xlsx_path": "out/report.xlsx",
  "pptx_path": "out/report.pptx",
  "docx_path": "out/report.docx",
  "workbook": {
    "sheets": [
      {
        "name": "Sheet1",
        "columns": [
          "A"
        ],
        "rows": [
          [
            1
          ]
        ]
      }
    ]
  },
  "deck": {
    "title": "Deck",
    "slides": [
      {
        "title": "S1",
        "bullets": [],
        "image_paths": [],
        "charts": []
      }
    ]
  },
  "doc": {
    "title": "Doc",
    "sections": [
      {
        "heading": "H",
        "paragraphs": [
          "P"
        ],
        "bullets": []
      }
    ]
  }
}
```
