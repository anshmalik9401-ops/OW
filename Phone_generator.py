import tkinter as tk
from tkinter import scrolledtext, messagebox
import random
import itertools
import csv
import io
import re
import math
import sys
import importlib
from pathlib import Path
from datetime import datetime, timedelta
from tkinter import filedialog
import pyperclip

class PhoneNumberGenerator:
    DATA_FILE = (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent) / "data.txt"

    def __init__(self, root):
        self.root = root
        self.root.title("Phone Number Record Generator")
        self.root.geometry("900x700")
        self.root.configure(bg='#f0f0f0')

        self.first_names =  [
    'Aarav', 'Aadhya', 'Vivaan', 'Aarohi', 'Aditya', 'Aditi', 'Arjun', 'Ananya',
    'Reyansh', 'Anika', 'Krishna', 'Anjali', 'Ishaan', 'Anushka', 'Shaurya', 'Avni',
    'Atharv', 'Diya', 'Advait', 'Isha', 'Kabir', 'Ishita', 'Rudra', 'Jiya',
    'Dhruv', 'Kavya', 'Rohan', 'Kiara', 'Kunal', 'Meera', 'Varun', 'Myra',
    'Nikhil', 'Naina', 'Akash', 'Navya', 'Abhishek', 'Neha', 'Ankit', 'Nidhi',
    'Amit', 'Pooja', 'Rahul', 'Priya', 'Rohit', 'Riya', 'Vikas', 'Saanvi',
    'Deepak', 'Sakshi', 'Sandeep', 'Sara', 'Manish', 'Shreya', 'Harsh', 'Simran',
    'Tarun', 'Sneha', 'Rajesh', 'Tanvi', 'Ravi', 'Tanya', 'Manoj', 'Trisha',
    'Vikram', 'Vanya', 'Sanjay', 'Aisha', 'Vijay', 'Alisha', 'Mukesh', 'Amrita',
    'Ashok', 'Anamika', 'Ajay', 'Anaya', 'Sunil', 'Anu', 'Prakash', 'Arpita',
    'Naveen', 'Bhavna', 'Pankaj', 'Charu', 'Gaurav', 'Deepa', 'Mohit', 'Divya',
    'Sumit', 'Garima', 'Sachin', 'Geeta', 'Yash', 'Gauri', 'Kartik', 'Harini',
    'Saurabh', 'Heena', 'Ritesh', 'Indu', 'Rakesh', 'Jyoti', 'Raghav', 'Kajal',
    'Madhav', 'Kalpana', 'Dev', 'Kanchan', 'Om', 'Karishma', 'Lakshya', 'Kashish',
    'Parth', 'Khushi', 'Ayaan', 'Komal', 'Zayan', 'Kriti', 'Rehan', 'Lavanya',
    'Faizan', 'Mahi', 'Armaan', 'Manisha', 'Sameer', 'Megha', 'Imran', 'Muskan',
    'Aamir', 'Namrata', 'Danish', 'Natasha', 'Farhan', 'Pallavi', 'Salman', 'Payal',
    'Irfan', 'Pragya', 'Junaid', 'Preeti', 'Adil', 'Radhika', 'Faisal', 'Ritu',
    'Tushar', 'Sanya', 'Chirag', 'Shalini', 'Darshan', 'Shikha', 'Harshit', 'Shweta',
    'Anurag', 'Sonal', 'Abhinav', 'Sonia', 'Akhil', 'Suman', 'Aman', 'Sunita',
    'Ansh', 'Swati', 'Anshul', 'Vaishali', 'Bharat', 'Vidhi', 'Bhavesh', 'Yashika',
    'Chetan', 'Zoya', 'Dheeraj', 'Ayesha', 'Gautam', 'Fatima', 'Hemant', 'Sana',
    'Jatin', 'Hiba', 'Keshav', 'Mahira', 'Lalit', 'Noor', 'Lokesh', 'Ruhi',
    'Mayank', 'Samaira', 'Nitin', 'Afreen', 'Pranav', 'Aakanksha', 'Prateek', 'Aanchal',
    'Pulkit', 'Aastha', 'Rishabh', 'Amisha', 'Shashank', 'Anushree', 'Shubham', 'Aparna',
    'Siddharth', 'Archana', 'Tejas', 'Bharti', 'Uday', 'Bhumika', 'Utkarsh', 'Chhavi',
    'Vaibhav', 'Damini', 'Varad', 'Devika', 'Vedant', 'Esha', 'Yuvraj', 'Falguni',
    'Karan', 'Ishani', 'Manav', 'Janvi', 'Neeraj', 'Kalyani', 'Nishant', 'Kamya',
    'Ojas', 'Kanika', 'Pratham', 'Mitali', 'Ranveer', 'Mrinal', 'Samar', 'Nandini',
    'Shaan', 'Nikita', 'Tanmay', 'Palak', 'Ujjwal', 'Parnika', 'Veer', 'Pranali',
    'Aadesh', 'Prerna', 'Anirudh', 'Rachna', 'Arnav', 'Rashi', 'Avinash', 'Reema',
    'Balram', 'Roshni', 'Bhuvan', 'Saumya', 'Daksh', 'Shambhavi', 'Eshan', 'Shruti',
    'Gagan', 'Srishti', 'Himanshu', 'Sukanya', 'Jaideep', 'Supriya', 'Kshitij', 'Surbhi',
    'Mahesh', 'Tripti', 'Naman', 'Urvashi', 'Omkar', 'Vibhuti', 'Prabhav', 'Yamini',
    'Raghunath', 'Yuvika', 'Shreyas', 'Zainab', 'Tapan', 'Apeksha', 'Trilok', 'Anagha',
    'Vatsal', 'Ankita', 'Yatin', 'Apoorva', 'Zubin', 'Barkha', 'Abhay', 'Chandni',
    'Akshat', 'Disha', 'Amar', 'Ekta', 'Amol', 'Ira', 'Anmol', 'Juhi',
    'Ashwin', 'Kirti', 'Bimal', 'Madhuri'
]

        self.last_names = [
            'Sharma', 'Verma', 'Mehta', 'Kapoor', 'Yadav', 'Gupta', 'Kumar', 'Mishra',
            'Arora', 'Singh', 'Malhotra', 'Agarwal', 'Jain', 'Patel', 'Bansal', 'Vohra',
            'Saini', 'Khanna', 'Goel', 'Reddy', 'Joshi', 'Nair', 'Shah', 'Menon',
            'Iyer', 'Rao', 'Desai', 'Pillai', 'Bhatt', 'Trivedi'
        ]

        self.email_domains = ['gmail.com', 'yahoo.com', 'outlook.com']

        self._name_pool = []
        self.pending_records = []
        self.rejected_rows = []
        self.selected_excel = None
        self.preview_text = ""

        self.create_widgets()

    def _refill_name_pool(self):
        all_pairs = list(itertools.product(self.first_names, self.last_names))
        random.shuffle(all_pairs)
        self._name_pool = all_pairs

    def get_unique_name(self):
        if not self._name_pool:
            self._refill_name_pool()
        return self._name_pool.pop()

    def create_widgets(self):
        title_label = tk.Label(
            self.root,
            text="📱 Phone Number Record Generator",
            font=('Arial', 18, 'bold'),
            bg='#f0f0f0',
            fg='#2c3e50'
        )
        title_label.pack(pady=15)

        input_frame = tk.Frame(self.root, bg='#f0f0f0')
        input_frame.pack(pady=10, padx=20, fill='x')

        instruction = tk.Label(
            input_frame,
            text="Upload Excel (Number and Category columns), or copy-paste one record per line: Number Category (e.g. 9876543210 Real Estate)",
            font=('Arial', 11),
            bg='#f0f0f0',
            fg='#34495e'
        )
        instruction.pack(anchor='w')

        self.input_text = scrolledtext.ScrolledText(
            input_frame,
            height=12,
            font=('Consolas', 10),
            wrap=tk.NONE,
            bg='white',
            fg='#2c3e50',
            relief=tk.GROOVE,
            bd=2
        )
        self.input_text.pack(pady=5, fill='both', expand=True)

        browse_btn = tk.Button(
            input_frame,
            text="Browse Excel (.xlsx / .xls)",
            font=('Arial', 10, 'bold'),
            command=self.browse_excel
        )
        browse_btn.pack(anchor='w', pady=4)

        button_frame = tk.Frame(self.root, bg='#f0f0f0')
        button_frame.pack(pady=10)

        generate_btn = tk.Button(
            button_frame,
            text="🚀 Import / Generate Records",
            font=('Arial', 12, 'bold'),
            bg='#3498db',
            fg='white',
            padx=30,
            pady=8,
            relief=tk.RAISED,
            bd=2,
            cursor='hand2',
            command=self.generate_records
        )
        generate_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = tk.Button(
            button_frame,
            text="🗑️ Clear All",
            font=('Arial', 11),
            bg='#e74c3c',
            fg='white',
            padx=20,
            pady=8,
            relief=tk.RAISED,
            bd=2,
            cursor='hand2',
            command=self.clear_all
        )
        clear_btn.pack(side=tk.LEFT, padx=5)

        copy_btn = tk.Button(
            button_frame,
            text="📋 Copy Output",
            font=('Arial', 11),
            bg='#2ecc71',
            fg='white',
            padx=20,
            pady=8,
            relief=tk.RAISED,
            bd=2,
            cursor='hand2',
            command=self.copy_output
        )
        copy_btn.pack(side=tk.LEFT, padx=5)

        output_label = tk.Label(
            self.root,
            text="Generated Records:",
            font=('Arial', 11),
            bg='#f0f0f0',
            fg='#34495e'
        )
        output_label.pack(anchor='w', padx=20)

        self.output_text = scrolledtext.ScrolledText(
            self.root,
            height=20,
            font=('Consolas', 10),
            wrap=tk.NONE,
            bg='white',
            fg='#2c3e50',
            relief=tk.GROOVE,
            bd=2
        )
        self.output_text.pack(pady=5, padx=20, fill='both', expand=True)

        self.status_label = tk.Label(
            self.root,
            text="Ready",
            font=('Arial', 9),
            bg='#f0f0f0',
            fg='#7f8c8d',
            anchor='w'
        )
        self.status_label.pack(side=tk.BOTTOM, fill='x', padx=20, pady=5)

    def generate_valid_date(self, used_dates):
        today = datetime.now().date()

        for _ in range(100):
            days_back = random.randint(0, 60)
            random_date = today - timedelta(days=days_back)

            if random_date.weekday() != 6:
                date_str = random_date.strftime('%Y-%m-%d')
                if date_str not in used_dates:
                    return date_str

        date = today - timedelta(days=1)
        while date.weekday() == 6:
            date -= timedelta(days=1)
        return date.strftime('%Y-%m-%d')

    def generate_records(self):
        try:
            input_data = self.input_text.get('1.0', tk.END).strip()
            if self.selected_excel is not None and input_data == self.preview_text:
                imported_rows = self.pending_records
                rejected_rows = self.rejected_rows
            else:
                if not input_data:
                    messagebox.showwarning("Warning", "Upload an Excel file or enter phone numbers first!")
                    return
                imported_rows, rejected_rows = self.parse_pasted_numbers(input_data)

            if not imported_rows:
                self.show_import_summary([], rejected_rows)
                messagebox.showwarning("No records imported", "No valid, unique records were found.")
                return

            self.status_label.config(text=f"Generating records for {len(imported_rows)} numbers...")
            self.root.update()

            records = []
            used_dates = set()
            self._refill_name_pool()

            for row in imported_rows:
                date = self.generate_valid_date(used_dates)
                used_dates.add(date)
                first_name, last_name = self.get_unique_name()
                name = f"{first_name} {last_name}"
                domain = random.choice(self.email_domains)
                email = f"{first_name.lower()}.{last_name.lower()}@{domain}"
                records.append({
                    'Name': name,
                    'Email': email,
                    'Number': row['Number'],
                    'Date': date,
                    'Category': row['Category'],
                })

            output = self.format_output(records)
            try:
                with self.DATA_FILE.open("w", encoding="utf-8", newline="") as destination:
                    destination.write(output)
                save_ok = True
            except Exception as save_err:
                messagebox.showerror("Save Error", f"Records could not be saved to data.txt:\n{save_err}")
                save_ok = False

            if save_ok:
                self.show_import_summary(records, rejected_rows)
                self.status_label.config(
                    text=(
                        f"✅ Imported {len(records)} records; {len(rejected_rows)} rejected — "
                        f"{self.DATA_FILE.name} replaced with new data"
                    ),
                    fg='#27ae60'
                )
                self.pending_records = []
                self.rejected_rows = []
                messagebox.showinfo(
                    "Import complete",
                    f"Records imported: {len(records)}\n"
                    f"Rejected: {len(rejected_rows)}\n"
                    f"Previous data replaced in: {self.DATA_FILE}"
                )
                self.root.destroy()
            else:
                self.status_label.config(text="❌ Save failed — see error popup", fg='#e74c3c')

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred:\n{str(e)}")
            self.status_label.config(text="❌ Error occurred", fg='#e74c3c')

    @staticmethod
    def _cell_text(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    @classmethod
    def _normalize_number(cls, value):
        text = cls._cell_text(value)
        return ''.join(re.findall(r'\d', text))

    def browse_excel(self):
        filepath = filedialog.askopenfilename(
            title="Select phone number Excel file",
            filetypes=[
                ("Excel workbook (*.xlsx)", "*.xlsx"),
                ("Excel 97-2003 workbook (*.xls)", "*.xls"),
                ("All files", "*.*"),
            ]
        )
        if not filepath:
            return

        try:
            parsed, rejected = self.parse_excel_file(filepath)
            self.pending_records = parsed
            self.rejected_rows = rejected
            self.selected_excel = filepath
            self.input_text.delete('1.0', tk.END)
            self.input_text.insert('1.0', self.format_preview(parsed, rejected))
            self.preview_text = self.input_text.get('1.0', tk.END).strip()
            self.status_label.config(
                text=f"Preview: {len(parsed)} valid record(s), {len(rejected)} rejected — click Import / Generate Records to save",
                fg='#34495e'
            )
        except ImportError as error:
            package = "openpyxl" if Path(filepath).suffix.lower() == ".xlsx" else "xlrd"
            self.pending_records = []
            self.rejected_rows = []
            self.selected_excel = None
            self.input_text.delete('1.0', tk.END)
            messagebox.showerror(
                "Missing package",
                f"Reading this Excel format requires {package}.\nInstall project packages with:\npy -m pip install -r requirements.txt\n\n{error}"
            )
        except Exception as error:
            self.pending_records = []
            self.rejected_rows = []
            self.selected_excel = None
            self.input_text.delete('1.0', tk.END)
            messagebox.showerror("Excel import error", f"Could not read the selected workbook:\n{error}")

    @classmethod
    def parse_excel_file(cls, filepath):
        extension = Path(filepath).suffix.lower()
        workbook = None
        if extension == ".xlsx":
            from openpyxl import load_workbook
            workbook = load_workbook(filepath, read_only=True, data_only=True)
            worksheet = workbook.active
            rows = worksheet.iter_rows(values_only=True)
            header = next(rows, None)
        elif extension == ".xls":
            xlrd = importlib.import_module("xlrd")
            workbook = xlrd.open_workbook(filepath, on_demand=True)
            worksheet = workbook.sheet_by_index(0)
            header = worksheet.row_values(0) if worksheet.nrows else None
            rows = (worksheet.row_values(index) for index in range(1, worksheet.nrows))
        else:
            raise ValueError("Please select an .xlsx or .xls file.")

        try:
            if not header:
                raise ValueError("The selected Excel sheet is empty.")
            headers = [cls._cell_text(value).strip().casefold() for value in header]
            if "number" not in headers or "category" not in headers:
                raise ValueError("The first row must contain both Number and Category columns.")
            number_index = headers.index("number")
            category_index = headers.index("category")
            parsed = []
            rejected = []
            seen = set()
            for row_number, values in enumerate(rows, start=2):
                values = list(values)
                number_value = values[number_index] if number_index < len(values) else None
                category_value = values[category_index] if category_index < len(values) else None
                number = cls._normalize_number(number_value)
                category = re.sub(r'\s+', ' ', cls._cell_text(category_value)).strip()
                if not number and not category:
                    continue
                if not number:
                    rejected.append(f"Row {row_number}: empty or invalid Number")
                    continue
                if len(number) != 10:
                    rejected.append(f"Row {row_number}: Number must contain exactly 10 digits ({number})")
                    continue
                if not category:
                    rejected.append(f"Row {row_number}: empty Category for {number}")
                    continue
                if number in seen:
                    rejected.append(f"Row {row_number}: duplicate number {number} in uploaded file")
                    continue
                seen.add(number)
                parsed.append({'Number': number, 'Category': category, 'row': row_number})
            return parsed, rejected
        finally:
            if workbook is not None and hasattr(workbook, "close"):
                workbook.close()

    def parse_pasted_numbers(self, input_data):
        rows = []
        rejected = []
        seen = set()
        for row_number, line in enumerate(input_data.splitlines(), start=1):
            if not line.strip():
                continue
            if re.fullmatch(r'\s*-{3,}\s*', line) or re.match(r'\s*(Valid preview:|Row \d+:)', line):
                continue
            if re.search(r'\bnumber\b', line, re.IGNORECASE) and re.search(
                r'\b(category|type)\b', line, re.IGNORECASE
            ):
                continue
            matches = list(re.finditer(r'(?<!\d)(?:\+?91[\s-]?)?(\d{10})(?!\d)', line))
            if not matches:
                rejected.append(f"Line {row_number}: empty or invalid Number")
                continue
            if len(matches) > 1:
                rejected.append(f"Line {row_number}: multiple phone numbers found")
                continue

            match = matches[0]
            number = match.group(1)
            category = f"{line[:match.start()]} {line[match.end():]}"
            category = re.sub(r'\b(number|phone|mobile|category|type)\b\s*[:=]?', ' ', category, flags=re.IGNORECASE)
            category = re.sub(r'[\t,;|]+', ' ', category)
            category = re.sub(r'\s+', ' ', category).strip(' :-')
            category = category or 'Real Estate'
            if number in seen:
                rejected.append(f"Line {row_number}: duplicate number {number} in input")
                continue
            seen.add(number)
            rows.append({'Number': number, 'Category': category, 'row': row_number})
        return rows, rejected

    def format_preview(self, records, rejected):
        lines = ["Number       Category", "------------------------------"]
        lines.extend(f"{row['Number']:<12} {row['Category']}" for row in records)
        lines.append(f"\nValid preview: {len(records)} | Rejected: {len(rejected)}")
        lines.extend(rejected)
        return "\n".join(lines)

    def show_import_summary(self, records, rejected):
        lines = [
            self.format_output(records),
            f"\nRecords imported: {len(records)}",
        ]
        if rejected:
            lines.append(f"Rejected records ({len(rejected)}):")
            lines.extend(rejected)
        self.output_text.delete('1.0', tk.END)
        self.output_text.insert('1.0', "\n".join(lines))

    def format_output(self, records):
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=['Name', 'Email', 'Number', 'Date', 'Category'],
            delimiter='\t',
            lineterminator='\n',
        )
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, '') for field in writer.fieldnames})
        return output.getvalue().rstrip('\n')

    def clear_all(self):
        self.input_text.delete('1.0', tk.END)
        self.output_text.delete('1.0', tk.END)
        self.pending_records = []
        self.rejected_rows = []
        self.selected_excel = None
        self.status_label.config(text="Cleared all fields", fg='#7f8c8d')

    def copy_output(self):
        output = self.output_text.get('1.0', tk.END).strip()
        if output:
            pyperclip.copy(output)
            self.status_label.config(text="✅ Output copied to clipboard!", fg='#27ae60')
            messagebox.showinfo("Success", "Output copied to clipboard!")
        else:
            messagebox.showwarning("Warning", "No output to copy!")

if __name__ == "__main__":
    root = tk.Tk()
    app = PhoneNumberGenerator(root)
    root.mainloop()