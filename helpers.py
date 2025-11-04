import csv
import os
import re

def fix_subject_name_in_csv(csv_path, real_subject=None):
    """
    Automatically replaces incorrect 'Computer Science' subject names
    in a downloaded result CSV and renames the file.
    If `real_subject` is provided, that name is used directly.
    """

    if not os.path.exists(csv_path):
        print(f"❌ File not found: {csv_path}")
        return csv_path

    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # Auto-detect subject if not provided
    if not real_subject:
        real_subject = None
        header_lower = [h.lower() for h in header]

        if 'subject' in header_lower:
            subject_index = header_lower.index('subject')
            for row in rows:
                subj = row[subject_index].strip()
                if subj and subj.lower() != 'computer science':
                    real_subject = subj
                    break
        elif 'exam title' in header_lower:
            title_index = header_lower.index('exam title')
            possible = rows[0][title_index].strip()
            if possible:
                real_subject = re.sub(r'\s+exam.*', '', possible, flags=re.I)

    if not real_subject:
        print("⚠️ Could not detect the real subject name — using original filename.")
        return csv_path

    # Replace “Computer Science” with detected subject name
    fixed_rows = []
    for row in rows:
        fixed = [real_subject if c.strip().lower() == "computer science" else c for c in row]
        fixed_rows.append(fixed)

    # Save as new file
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", real_subject)
    new_path = os.path.join(os.path.dirname(csv_path), f"{safe_name}_Results.csv")

    with open(new_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(fixed_rows)

    print(f"✅ Fixed subject: {real_subject} → Saved as {os.path.basename(new_path)}")
    return new_path
