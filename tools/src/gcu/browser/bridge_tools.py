"""Tool schemas for the bridge remote HTTP API (port 9230)."""

TOOL_SCHEMAS: dict[str, dict] = {
    "browser_click": {
        "description": "Click an element on the page.",
        "params": {
            "selector": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "button": {"type": "string", "default": "left", "enum": ["left", "right", "middle"]},
            "double_click": {"type": "boolean", "default": False},
            "timeout_ms": {"type": "integer", "default": 5000},
        },
    },
    "browser_click_coordinate": {
        "description": "Click at specific viewport coordinates (CSS pixels).",
        "params": {
            "x": {"type": "number", "required": True},
            "y": {"type": "number", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "button": {"type": "string", "default": "left"},
        },
    },
    "browser_type": {
        "description": "Type text into an input element.",
        "params": {
            "selector": {"type": "string", "required": True},
            "text": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "delay_ms": {"type": "integer", "default": 1},
            "clear_first": {"type": "boolean", "default": True},
            "timeout_ms": {"type": "integer", "default": 30000},
            "use_insert_text": {"type": "boolean", "default": True},
        },
    },
    "browser_fill": {
        "description": "Fill an input element (clears existing content first).",
        "params": {
            "selector": {"type": "string", "required": True},
            "value": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 30000},
        },
    },
    "browser_type_focused": {
        "description": (
            "Type text into the already-focused element. Use after browser_click_coordinate "
            "has focused the target. Faster than browser_press for multi-character input."
        ),
        "params": {
            "text": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "delay_ms": {"type": "integer", "default": 1},
            "clear_first": {"type": "boolean", "default": True},
            "use_insert_text": {"type": "boolean", "default": True},
        },
    },
    "browser_press": {
        "description": "Press a keyboard key, optionally with modifiers.",
        "params": {
            "key": {"type": "string", "required": True},
            "selector": {"type": "string"},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "modifiers": {"type": "array", "items": "string"},
        },
    },
    "browser_press_at": {
        "description": "Move mouse to coordinates then press a key.",
        "params": {
            "x": {"type": "number", "required": True},
            "y": {"type": "number", "required": True},
            "key": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_navigate": {
        "description": "Navigate a tab to a URL.",
        "params": {
            "url": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "wait_until": {"type": "string", "default": "load"},
        },
    },
    "browser_go_back": {
        "description": "Navigate back in browser history.",
        "params": {
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_go_forward": {
        "description": "Navigate forward in browser history.",
        "params": {
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_reload": {
        "description": "Reload the current page.",
        "params": {
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_scroll": {
        "description": "Scroll the page.",
        "params": {
            "direction": {"type": "string", "default": "down", "enum": ["up", "down", "left", "right"]},
            "amount": {"type": "integer", "default": 500},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_hover": {
        "description": "Hover over an element.",
        "params": {
            "selector": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 30000},
        },
    },
    "browser_hover_coordinate": {
        "description": "Hover at CSS pixel coordinates.",
        "params": {
            "x": {"type": "number", "required": True},
            "y": {"type": "number", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_select": {
        "description": "Select option(s) in a dropdown.",
        "params": {
            "selector": {"type": "string", "required": True},
            "values": {"type": "array", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_screenshot": {
        "description": "Take a screenshot of the page (returns base64 PNG).",
        "params": {
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "full_page": {"type": "boolean", "default": False},
        },
    },
    "browser_snapshot": {
        "description": "Get the accessibility tree snapshot of the page.",
        "params": {
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_evaluate": {
        "description": "Evaluate JavaScript in the page.",
        "params": {
            "expression": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_get_text": {
        "description": "Get text content of an element.",
        "params": {
            "selector": {"type": "string", "required": True},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
        },
    },
    "browser_wait": {
        "description": "Wait for an element or text to appear on the page.",
        "params": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "tab_id": {"type": "integer"},
            "profile": {"type": "string"},
            "timeout_ms": {"type": "integer", "default": 30000},
        },
    },
}
