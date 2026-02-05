import pandas as pd
import json
import yaml
import xmltodict
import os
from typing import Any, Dict, Optional, List

def convert_data_format(input_path: str, output_format: str, options: Optional[Dict[str, Any]] = None) -> str:
    """
    Converts data between different formats (CSV, JSON, XML, YAML).
    Returns a success message with the new file path or an error message.
    """
    options = options or {}
    if not os.path.exists(input_path):
        return f"Error: Input file '{input_path}' not found."

    filename, ext = os.path.splitext(input_path)
    input_format = ext.lower().replace('.', '')
    output_format = output_format.lower().replace('.', '')
    output_path = f"{filename}.{output_format}"

    try:
        # --- PHASE 1: Data Ingestion ---
        if input_format == 'csv':
            data_frame = pd.read_csv(input_path)
            data = data_frame.to_dict(orient='records')
        elif input_format == 'json':
            with open(input_path, 'r') as f:
                data = json.load(f)
        elif input_format == 'yaml' or input_format == 'yml':
            with open(input_path, 'r') as f:
                data = yaml.safe_load(f)
        elif input_format == 'xml':
            with open(input_path, 'r') as f:
                data = xmltodict.parse(f.read())
        else:
            return f"Error: Unsupported input format '{input_format}'"

        # --- PHASE 2: Data Export ---
        if output_format == 'json':
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=options.get('indent', 2))
        elif output_format == 'csv':
            df_to_save = pd.DataFrame(data)
            df_to_save.to_csv(output_path, index=False)
        elif output_format == 'yaml':
            with open(output_path, 'w') as f:
                yaml.dump(data, f, default_flow_style=False)
        elif output_format == 'xml':
            root_element = options.get('root', 'root')
            with open(output_path, 'w') as f:
                f.write(xmltodict.unparse({root_element: data}, pretty=True))
        else:
            return f"Error: Unsupported output format '{output_format}'"

        return f"Successfully converted {input_path} to {output_path}"

    except Exception as e:
        return f"Conversion failed: {str(e)}"
