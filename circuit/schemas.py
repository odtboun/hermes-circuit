"""Tool schemas — what the model reads."""

from __future__ import annotations

BOARD_ARG = {
    "type": "string",
    "description": "Board id (slug). Omit to use the most recently updated board.",
}

CATALOG = {
    "name": "circuit_catalog",
    "description": (
        "Browse the Circuit part library and the starter designs. Call this before adding parts: "
        "only parts returned here exist, and each one lists its pin numbers (the keys you use in "
        "circuit_add_part's nets map). Templates are ready-made netlists you can instantiate with "
        "circuit_create(template=...)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text search, e.g. 'i2c sensor' or 'relay'."},
            "category": {"type": "string", "description": "Filter: passive, diode, transistor, power, ic, sensor, connector, switch, relay, audio, timing, module, mechanical, opto."},
        },
    },
}

CREATE = {
    "name": "circuit_create",
    "description": (
        "Create a new PCB project. Either start from a template (fast path, gives a complete "
        "working design) or from an empty board sized in millimetres. Returns the board id you "
        "pass to every later call. New boards are auto-placed; call circuit_route then "
        "circuit_export to finish."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Human title, e.g. 'Pico sensor hub'."},
            "template": {"type": "string", "description": "Template id from circuit_catalog, e.g. 'pico-blinky'."},
            "width": {"type": "number", "description": "Board width in mm (10-400). Ignored with a template."},
            "height": {"type": "number", "description": "Board height in mm (10-400). Ignored with a template."},
            "layers": {"type": "integer", "enum": [2], "description": "Layer count. This engine routes 2-layer boards."},
        },
        "required": ["title"],
    },
}

BOARDS = {
    "name": "circuit_boards",
    "description": "List every Circuit board project with its size, component count, routing and DRC status.",
    "parameters": {"type": "object", "properties": {}},
}

IMPORT = {
    "name": "circuit_import",
    "description": (
        "Open an existing KiCad board (.kicad_pcb, KiCad 6/7/8 and newer) as a read-only Circuit "
        "project so it can be inspected and rendered in the viewer. The board is parsed as-is: "
        "Edge.Cuts outline, footprints, pads, tracks, vias and nets become a view document — nothing "
        "is re-placed, re-routed or design-rule checked. Pass either a local `path` or a `url` "
        "(e.g. a raw.githubusercontent.com link to an open-source board). Returns the new board id; "
        "re-importing the same file or url replaces that project."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to a .kicad_pcb file."},
            "url": {"type": "string",
                    "description": "http(s) URL of a .kicad_pcb (raw file, not an HTML viewer page). "
                                   "Use instead of path."},
        },
        "required": [],
    },
}

BOARD = {
    "name": "circuit_board",
    "description": (
        "Read one board: components with their pin->net map, nets, routing status, ERC and DRC. "
        "Use it to inspect state before editing, or to answer questions about the design."
    ),
    "parameters": {"type": "object", "properties": {"board": BOARD_ARG}},
}

SAMPLES = {
    "name": "circuit_samples",
    "description": (
        "Browse and load bundled sample boards: real open-source KiCad designs (up to 309 "
        "footprints) that are downloaded from the upstream KiCad demo repository and imported "
        "read-only, so the viewer has something genuinely complex to render. action='list' "
        "shows the catalogue; action='load' with an id fetches and imports one (needs network)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "load"], "default": "list",
                       "description": "'list' the catalogue (default) or 'load' one sample."},
            "id": {"type": "string",
                   "description": "Sample id from action='list', e.g. 'tiny-tapeout'."},
        },
        "required": [],
    },
}


ADD_PART = {
    "name": "circuit_add_part",
    "description": (
        "Add a component to a board. 'part' is an id from circuit_catalog (e.g. 'r-0805', "
        "'ne555', 'pico'). 'nets' maps pin NUMBER -> net name, e.g. {\"1\": \"GND\", \"2\": \"LED_A\"}. "
        "Net names are free-form and case-insensitive; names like GND/VSS become the ground class "
        "and +3V3/5V/VCC/VIN the power class, which gives them wider traces. Pins you leave out are "
        "reported by DRC as unconnected."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": BOARD_ARG,
            "part": {"type": "string", "description": "Part id from circuit_catalog."},
            "ref": {"type": "string", "description": "Reference designator, e.g. 'R4'. Auto-assigned when omitted."},
            "value": {"type": "string", "description": "Value shown in the BOM, e.g. '10k', '100nF'."},
            "nets": {
                "type": "object",
                "description": "Pin number -> net name. Example: {\"1\": \"+3V3\", \"2\": \"GND\"}.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["part"],
    },
}

CONNECT = {
    "name": "circuit_connect",
    "description": (
        "Join pins onto nets. Each connection is a flat list [ref, pin, ref, pin, ...] and every "
        "pin in that list ends up on one net. If any pin already has a net, that name is reused; "
        "otherwise a name is generated. Use this to add a wire between existing parts, or to give "
        "a net you already created a better name with the optional 'net' argument."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": BOARD_ARG,
            "connections": {
                "type": "array",
                "description": "List of pin groups: [[\"U1\",\"GP15\",\"R1\",\"1\"], [\"R1\",\"2\",\"D1\",\"2\"]]",
                "items": {"type": "array", "items": {"type": "string"}},
            },
            "net": {"type": "string", "description": "Force the net name for every group in this call."},
        },
        "required": ["connections"],
    },
}

REMOVE_PART = {
    "name": "circuit_remove_part",
    "description": "Remove a component (and its pins from their nets) from a board.",
    "parameters": {
        "type": "object",
        "properties": {"board": BOARD_ARG, "ref": {"type": "string"}},
        "required": ["ref"],
    },
}

PLACE = {
    "name": "circuit_place",
    "description": (
        "Place components. With no 'positions' it runs the deterministic auto-placer (cluster by "
        "shared nets, biggest parts first, connectors to the edge). With 'positions' it moves the "
        "listed parts and leaves the rest alone. Placement always happens before routing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": BOARD_ARG,
            "positions": {
                "type": "array",
                "description": "Manual moves: [{\"ref\": \"U1\", \"x\": 30, \"y\": 20, \"rot\": 90}]",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "rot": {"type": "number"},
                    },
                    "required": ["ref", "x", "y"],
                },
            },
            "fit": {"type": "boolean", "description": "Grow the board outline so every part fits (default false)."},
        },
    },
}

ROUTE = {
    "name": "circuit_route",
    "description": (
        "Autoroute every net on 2 layers and run DRC. Routing is deterministic and rule-driven: "
        "trace width and clearance come from the board rules and net classes (power/ground nets are "
        "wider). Returns which nets routed, which failed and why, plus the DRC verdict. effort "
        "'fast' trades some quality for speed on dense boards."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": BOARD_ARG,
            "effort": {"type": "string", "enum": ["fast", "normal"], "description": "Routing effort (default normal)."},
        },
    },
}

CHECK = {
    "name": "circuit_check",
    "description": (
        "Run the electrical rule check (dangling nets, missing power/ground, courtyard overlaps, "
        "parts off-board) and the design rule check (clearance, minimum width/drill, annular ring, "
        "board-edge clearance, full net connectivity). Returns errors and warnings with coordinates."
    ),
    "parameters": {"type": "object", "properties": {"board": BOARD_ARG}},
}

EXPORT = {
    "name": "circuit_export",
    "description": (
        "Build the fabrication package: RS-274X Gerbers (copper, mask, silk, edge), Excellon drill "
        "files (plated + non-plated), a KiCad 8 project, a STEP AP214 model, BOM, pick-and-place, "
        "netlist, SVG/HTML preview and a hashed manifest. Routes first if the board is not routed. "
        "Returns the file list with sizes and the absolute export directory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": BOARD_ARG,
            "route": {"type": "boolean", "description": "Route before exporting (default true when unrouted)."},
        },
    },
}

DOCS = {
    "name": "circuit_docs",
    "description": (
        "Generate the board's documents and return a chat-ready preview directive for each: "
        "'shopping' (bill of materials with distributor search links per MPN), 'wiring' (pin → "
        "net → destination table per connector) and 'poster' (one-page board poster with the "
        "render, stats and top of the BOM). Files are written to the export folder. Emit the "
        "returned preview_directive on its own line to show the document inline in the chat."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": BOARD_ARG,
            "kind": {
                "type": "string",
                "enum": ["all", "shopping", "wiring", "poster"],
                "description": "Which document (default all).",
            },
        },
    },
}

VIEW = {
    "name": "circuit_view",
    "description": (
        "Open a board in the Hermes UI. Returns a transcript directive that renders the board "
        "inline in the chat (2D layer stackup, live) plus a standalone HTML preview path. Put the "
        "returned 'directive' on its own line in your reply so the user sees the board."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board": BOARD_ARG,
            "inline": {"type": "boolean", "description": "Include the chat directive (default true)."},
        },
    },
}

ALL = [CATALOG, CREATE, BOARDS, IMPORT, SAMPLES, BOARD, ADD_PART, CONNECT, REMOVE_PART, PLACE, ROUTE, CHECK, EXPORT, VIEW, DOCS]
NAMES = [s["name"] for s in ALL]
