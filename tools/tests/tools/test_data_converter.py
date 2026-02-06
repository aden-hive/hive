import unittest
import os
import json
import sys

# 1. Get the directory where this test file resides (tools/tests/tools/)
current_dir = os.path.dirname(os.path.abspath(__file__))

# 2. Construct the path to the source code (tools/src/aden_tools/)
# We go up two levels (../../) to reach the 'tools' root, then down to src/aden_tools
src_path = os.path.abspath(os.path.join(current_dir, '../../src/aden_tools'))

# 3. Add to system path so Python can import the module
sys.path.append(src_path)

from data_converter import convert_data_format

class TestDataConverter(unittest.TestCase):
    def setUp(self):
        """Set up temporary files for testing."""
        self.test_data = [{"id": 1, "name": "Agent Test"}]
        self.json_file = "test_input.json"
        self.csv_file = "test_input.csv"
        
        # Create a dummy JSON file
        with open(self.json_file, 'w') as f:
            json.dump(self.test_data, f)

    def tearDown(self):
        """Clean up temporary files after tests."""
        if os.path.exists(self.json_file):
            os.remove(self.json_file)
        if os.path.exists(self.csv_file):
            os.remove(self.csv_file)

    def test_json_to_csv_conversion(self):
        """Test that a JSON file is correctly converted to CSV."""
        result = convert_data_format(self.json_file, "csv")
        
        # Assertions
        self.assertIn("Successfully converted", result)
        self.assertTrue(os.path.exists(self.csv_file), "CSV output file was not created")

    def test_invalid_input(self):
        """Test error handling for non-existent input files."""
        result = convert_data_format("non_existent_file.json", "csv")
        self.assertIn("Error", result)

if __name__ == '__main__':
    unittest.main()