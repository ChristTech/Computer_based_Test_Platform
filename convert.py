import os
import pandas as pd

# Specify the folder path containing the text files
folder_path = "C:/Users/adebi/Desktop/TGGA/1st term/Third C.A test"  # Replace with the actual folder path

# Ensure the folder exists
if not os.path.isdir(folder_path):
    print(f"Error: The folder '{folder_path}' does not exist.")
    exit()

# Iterate through all files in the folder
for filename in os.listdir(folder_path):
    # Check if the file is a text file (you can modify the extension check as needed)
    if filename.endswith(".txt"):
        # Construct the full file path
        file_path = os.path.join(folder_path, filename)
        
        try:
            # Read the tab-separated text file into a pandas DataFrame
            df = pd.read_csv(file_path, sep="\t")
            
            # Create the output Excel file name (same name, different extension)
            output_filename = os.path.splitext(filename)[0] + ".xlsx"
            output_path = os.path.join(folder_path, output_filename)
            
            # Export the DataFrame to an Excel file
            df.to_excel(output_path, index=False, sheet_name="Sheet1")
            
            print(f"Converted '{filename}' to '{output_filename}'")
            
        except Exception as e:
            print(f"Error processing '{filename}': {str(e)}")

print("Conversion process completed.")