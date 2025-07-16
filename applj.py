from flask import Flask, render_template, request, redirect, url_for, session
import hashlib
import os
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import csv
from flask import Response, make_response
from io import StringIO
import io
from xhtml2pdf import pisa

app = Flask(__name__, template_folder=os.path.join(os.getcwd(), "templates"))
app.secret_key = os.urandom(24)

# Data user (dalam implementasi nyata, gunakan database)
USERS = {
    "admin": {"password": "admin123", "role": "Administrator"},
    "airnav1": {"password": "airnav123", "role": "Staff 1"},
    "airnav2": {"password": "airnav456", "role": "Staff 2"},
    "guest": {"password": "guest123", "role": "Guest User"}
}

# Authenticate with Google Sheets
def authenticate_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(r"C:\Users\Asus\Downloads\acc\kp-cro-e2b6f8ff4bea..json", scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key("116WPS31DLPID0_T4G6vkMnplAPvyMp4rcnO5-TTjySM").sheet1
    return sheet

# Get new ID for input
def get_new_id(sheet):
    records = sheet.get_all_records()
    if not records:
        return 1
    # Cari key id/ID/Id secara fleksibel
    def get_id(record):
        return record.get('id') or record.get('ID') or record.get('Id')
    id_list = [int(get_id(record)) for record in records if get_id(record) is not None and str(get_id(record)).isdigit()]
    if not id_list:
        return 1
    last_id = max(id_list)
    return last_id + 1

# Halaman Login
@app.route("/", methods=["GET", "POST"])
def login():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username in USERS and USERS[username]["password"] == password:
            session['logged_in'] = True
            session['username'] = username
            session['role'] = USERS[username]["role"]
            return redirect(url_for('dashboard'))
        else:
            return "Invalid username or password!"
    
    return render_template("index.html")

# Dashboard utama setelah login
@app.route("/dashboard")
def dashboard():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    sheet = authenticate_google_sheets()
    kunjungan_data = sheet.get_all_records()
    # Filter hanya data milik user yang login
    user_kunjungan = [k for k in kunjungan_data if k.get('username') == session['username']]
    total_kunjungan = len(user_kunjungan)
    # Rekap per bulan dan tujuan
    from collections import Counter
    bulan_counter = Counter()
    tujuan_counter = Counter()
    for k in user_kunjungan:
        tgl = k.get('tanggal_kunjungan', '')
        tujuan = k.get('tujuan_kunjungan', '-')
        try:
            if tgl:
                dt = datetime.strptime(tgl, '%Y-%m-%d')
                nama_bulan = dt.strftime('%B %Y')
                bulan_counter[nama_bulan] += 1
        except Exception:
            pass
        tujuan_counter[tujuan] += 1
    bulan_labels = sorted(bulan_counter.keys(), key=lambda x: datetime.strptime(x, '%B %Y'))
    bulan_values = [bulan_counter[bln] for bln in bulan_labels]
    tujuan_labels = list(tujuan_counter.keys())
    tujuan_values = [tujuan_counter[tj] for tj in tujuan_labels]
    # Data tabel
    data_kunjungan = []
    for k in user_kunjungan:
        data_kunjungan.append(type('Kunjungan', (), {
            'tanggal': k.get('tanggal_kunjungan', ''),
            'nama': k.get('nama_company', ''),
            'tujuan': k.get('tujuan_kunjungan', ''),
            'keterangan': k.get('notes', '')
        }))
    return render_template(
        "dashboard.html",
        username=session['username'],
        role=session['role'],
        total_kunjungan=total_kunjungan,
        bulan_labels=bulan_labels,
        bulan_values=bulan_values,
        tujuan_labels=tujuan_labels,
        tujuan_values=tujuan_values,
        bulan_data=zip(bulan_labels, bulan_values),
        tujuan_data=zip(tujuan_labels, tujuan_values),
        data_kunjungan=data_kunjungan
    )

# Halaman Input Kunjungan

@app.route("/input_kunjungan", methods=["GET", "POST"])
def input_kunjungan():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    if request.method == "POST":
        sheet = authenticate_google_sheets()
        id = get_new_id(sheet)

        # Handle file upload
        foto_url = ''
        if 'foto' in request.files and request.files['foto'].filename:
            foto = request.files['foto']
            ext = os.path.splitext(foto.filename)[1]
            filename = f"foto_{id}{ext}"
            save_path = os.path.join('static', 'uploads', filename)
            foto.save(save_path)
            foto_url = f"/static/uploads/{filename}"

        # Extract form data
        data = {
            "id": id,
            "username": session['username'],
            "nama_company": request.form['nama_company'],
            "kontak_nama": request.form['kontak_nama'],
            "tanggal_kunjungan": request.form['tanggal_kunjungan'],
            "waktu_kunjungan": request.form['waktu_kunjungan'],
            "tujuan_kunjungan": request.form['tujuan_kunjungan'],
            "notes": request.form['notes'],
            "foto_url": foto_url
        }

        row = [data["id"], data["username"], data["nama_company"], data["kontak_nama"],
               data["tanggal_kunjungan"], data["waktu_kunjungan"], data["tujuan_kunjungan"],
               data["notes"], data["foto_url"]]
        sheet.append_row(row)

        return redirect(url_for('data_management'))

    return render_template("input_kunjungan.html")

# Halaman Manajemen Data Kunjungan
@app.route('/data_management', methods=['GET'])
def data_management():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    sheet = authenticate_google_sheets()
    kunjungan_data = sheet.get_all_records()

    # Get filter parameters
    search_company = request.args.get('search_company', '').lower()
    filter_tujuan = request.args.get('filter_tujuan', 'Semua')
    filter_user = request.args.get('filter_user', 'Semua')
    sort_by = request.args.get('sort_by', 'tanggal_kunjungan')
    filter_bulan = request.args.get('filter_bulan', 'Semua')

    # Pastikan setiap record punya key 'id', jika tidak, skip
    def safe_int(val):
        try:
            return int(val)
        except:
            return None

    cleaned_data = []
    for k in kunjungan_data:
        # Normalisasi key jika perlu (misal: 'id', 'Id', 'ID')
        id_val = k.get('id') or k.get('ID') or k.get('Id')
        if id_val is not None:
            k['id'] = safe_int(id_val)
            # Tambahkan nama bulan (misal: Juli 2025) dari tanggal_kunjungan
            tgl = k.get('tanggal_kunjungan', '')
            try:
                if tgl:
                    dt = datetime.strptime(tgl, '%Y-%m-%d')
                    k['nama_bulan'] = dt.strftime('%B %Y')
                else:
                    k['nama_bulan'] = '-'
            except Exception:
                k['nama_bulan'] = '-'
            # Pastikan key foto_url ada
            k['foto_url'] = k.get('foto_url', '')
            cleaned_data.append(k)

    filtered_data = cleaned_data
    if search_company:
        filtered_data = [k for k in filtered_data if search_company in k.get('nama_company', '').lower()]
    if filter_tujuan != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('tujuan_kunjungan') == filter_tujuan]
    if filter_user != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('username') == filter_user]
    if filter_bulan != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('nama_bulan') == filter_bulan]


    # Apply sorting/filtering
    if sort_by == 'tanggal_kunjungan':
        filtered_data = sorted(filtered_data, key=lambda x: x.get('tanggal_kunjungan', ''), reverse=True)
    elif sort_by == 'per_bulan':
        # Group data per bulan (YYYY-MM)
        from collections import defaultdict
        bulan_dict = defaultdict(list)
        for k in filtered_data:
            tgl = k.get('tanggal_kunjungan', '')
            if tgl:
                bulan = tgl[:7]  # Ambil format YYYY-MM
                bulan_dict[bulan].append(k)
        # Urutkan bulan terbaru ke terlama
        filtered_data = []
        for bulan in sorted(bulan_dict.keys(), reverse=True):
            filtered_data.extend(bulan_dict[bulan])

    # Get current month's data
    current_month = datetime.now().strftime('%Y-%m')
    kunjungan_bulan_ini = [
        k for k in filtered_data if current_month in k.get('tanggal_kunjungan', '')
    ]

    # Get most common tujuan
    from collections import Counter
    tujuan_counter = Counter(
        k.get('tujuan_kunjungan', '-') for k in filtered_data
    )
    tujuan_terbanyak = tujuan_counter.most_common(1)[0][0] if tujuan_counter else "-"


    # Get unique values for filters
    unique_tujuan = sorted(list(set(k.get('tujuan_kunjungan', '') for k in cleaned_data)))
    unique_users = sorted(list(set(k.get('username', '') for k in cleaned_data)))
    unique_bulan = sorted(list(set(k.get('nama_bulan', '') for k in cleaned_data if k.get('nama_bulan') != '-')), key=lambda x: datetime.strptime(x, '%B %Y'), reverse=True)

    return render_template(
        "data_management.html",
        kunjungan_data=filtered_data,
        total_bulan_ini=len(kunjungan_bulan_ini),
        tujuan_terbanyak=tujuan_terbanyak,
        unique_tujuan=unique_tujuan,
        unique_users=unique_users,
        unique_bulan=unique_bulan,
        filter_bulan=filter_bulan
    )

# Halaman Monitoring
@app.route('/monitoring')
def monitoring():
    return render_template("monitoring.html")

# Halaman Visualization
@app.route('/visualization')
def visualization():
    sheet = authenticate_google_sheets()
    kunjungan_data = sheet.get_all_records()
    # Hitung jumlah kunjungan per bulan dan per tujuan
    from collections import Counter, defaultdict
    bulan_counter = Counter()
    tujuan_counter = Counter()
    for k in kunjungan_data:
        tgl = k.get('tanggal_kunjungan', '')
        tujuan = k.get('tujuan_kunjungan', '-')
        try:
            if tgl:
                dt = datetime.strptime(tgl, '%Y-%m-%d')
                nama_bulan = dt.strftime('%B %Y')
                bulan_counter[nama_bulan] += 1
        except Exception:
            pass
        tujuan_counter[tujuan] += 1
    # Urutkan bulan secara kronologis
    bulan_labels = sorted(bulan_counter.keys(), key=lambda x: datetime.strptime(x, '%B %Y'))
    bulan_values = [bulan_counter[bln] for bln in bulan_labels]
    tujuan_labels = list(tujuan_counter.keys())
    tujuan_values = [tujuan_counter[tj] for tj in tujuan_labels]
    return render_template(
        "visualization.html",
        bulan_labels=bulan_labels,
        bulan_values=bulan_values,
        tujuan_labels=tujuan_labels,
        tujuan_values=tujuan_values
    )

# Halaman Edit Kunjungan
@app.route('/edit_kunjungan/<int:id>', methods=['GET', 'POST'])
def edit_kunjungan(id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    sheet = authenticate_google_sheets()
    kunjungan = next((k for k in sheet.get_all_records() if k["id"] == id), None)

    if request.method == "POST":
        kunjungan["nama_company"] = request.form['nama_company']
        kunjungan["kontak_nama"] = request.form['kontak_nama']
        kunjungan["tanggal_kunjungan"] = request.form['tanggal_kunjungan']
        kunjungan["waktu_kunjungan"] = request.form['waktu_kunjungan']
        kunjungan["tujuan_kunjungan"] = request.form['tujuan_kunjungan']
        kunjungan["notes"] = request.form['notes']
        # Update on Google Sheets (Assuming sheet.update_cell exists)
        for i, k in enumerate(sheet.get_all_records(), start=2):
            if k["id"] == id:
                sheet.update_cell(i, 1, kunjungan["id"])
                sheet.update_cell(i, 2, kunjungan["username"])
                sheet.update_cell(i, 3, kunjungan["nama_company"])
                sheet.update_cell(i, 4, kunjungan["nama_kontak"])
                sheet.update_cell(i, 5, kunjungan["tanggal_kunjungan"])
                sheet.update_cell(i, 6, kunjungan["waktu_kunjungan"])
                sheet.update_cell(i, 7, kunjungan["tujuan_kunjungan"])
                sheet.update_cell(i, 8, kunjungan["notes"])
        return redirect(url_for('data_management'))

    return render_template('edit_kunjungan.html', kunjungan=kunjungan)

# Halaman Delete Kunjungan
@app.route('/delete_kunjungan/<int:id>', methods=['GET'])
def delete_kunjungan(id):
    sheet = authenticate_google_sheets()
    kunjungan_data = sheet.get_all_records()
    
    remaining_data = [k for k in kunjungan_data if k["id"] != id]
    sheet.delete_rows(id + 1)

    for i, row in enumerate(remaining_data, start=2):
        sheet.update_cell(i, 1, row["id"])
        sheet.update_cell(i, 2, row["username"])
        sheet.update_cell(i, 3, row["nama_company"])
        sheet.update_cell(i, 4, row["nama_kontak"])
        sheet.update_cell(i, 5, row["tanggal_kunjungan"])
        sheet.update_cell(i, 6, row["waktu_kunjungan"])
        sheet.update_cell(i, 7, row["tujuan_kunjungan"])
        sheet.update_cell(i, 8, row["notes"])

    return redirect(url_for('data_management'))


# Route Export CSV (mengikuti filter)
@app.route('/export_csv')
def export_csv():
    sheet = authenticate_google_sheets()
    kunjungan_data = sheet.get_all_records()
    # Ambil parameter filter dari GET
    search_company = request.args.get('search_company', '').lower()
    filter_tujuan = request.args.get('filter_tujuan', 'Semua')
    filter_user = request.args.get('filter_user', 'Semua')
    filter_bulan = request.args.get('filter_bulan', 'Semua')

    def safe_int(val):
        try:
            return int(val)
        except:
            return None

    cleaned_data = []
    for k in kunjungan_data:
        id_val = k.get('id') or k.get('ID') or k.get('Id')
        if id_val is not None:
            k['id'] = safe_int(id_val)
            tgl = k.get('tanggal_kunjungan', '')
            try:
                if tgl:
                    dt = datetime.strptime(tgl, '%Y-%m-%d')
                    k['nama_bulan'] = dt.strftime('%B %Y')
                else:
                    k['nama_bulan'] = '-'
            except Exception:
                k['nama_bulan'] = '-'
            cleaned_data.append(k)

    filtered_data = cleaned_data
    if search_company:
        filtered_data = [k for k in filtered_data if search_company in k.get('nama_company', '').lower()]
    if filter_tujuan != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('tujuan_kunjungan') == filter_tujuan]
    if filter_user != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('username') == filter_user]
    if filter_bulan != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('nama_bulan') == filter_bulan]

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Company', 'Kontak', 'Tanggal', 'Waktu', 'Tujuan', 'Notes'])
    for record in filtered_data:
        writer.writerow([
            record.get('nama_company',''),
            record.get('nama_kontak',''),
            record.get('tanggal_kunjungan',''),
            record.get('waktu_kunjungan',''),
            record.get('tujuan_kunjungan',''),
            record.get('notes','')
        ])
    output.seek(0)
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=kunjungan_data.csv'})


# Route Export PDF (mengikuti filter)
@app.route('/export_pdf')
def export_pdf():
    sheet = authenticate_google_sheets()
    kunjungan_data = sheet.get_all_records()
    user = session.get('username', '-')
    role = session.get('role', '-')
    # Ambil parameter filter dari GET
    search_company = request.args.get('search_company', '').lower()
    filter_tujuan = request.args.get('filter_tujuan', 'Semua')
    filter_user = request.args.get('filter_user', 'Semua')
    filter_bulan = request.args.get('filter_bulan', 'Semua')

    def safe_int(val):
        try:
            return int(val)
        except:
            return None

    cleaned_data = []
    for k in kunjungan_data:
        id_val = k.get('id') or k.get('ID') or k.get('Id')
        if id_val is not None:
            k['id'] = safe_int(id_val)
            tgl = k.get('tanggal_kunjungan', '')
            try:
                if tgl:
                    dt = datetime.strptime(tgl, '%Y-%m-%d')
                    k['nama_bulan'] = dt.strftime('%B %Y')
                else:
                    k['nama_bulan'] = '-'
            except Exception:
                k['nama_bulan'] = '-'
            cleaned_data.append(k)

    filtered_data = cleaned_data
    if search_company:
        filtered_data = [k for k in filtered_data if search_company in k.get('nama_company', '').lower()]
    if filter_tujuan != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('tujuan_kunjungan') == filter_tujuan]
    if filter_user != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('username') == filter_user]
    if filter_bulan != 'Semua':
        filtered_data = [k for k in filtered_data if k.get('nama_bulan') == filter_bulan]

    # Siapkan HTML sederhana untuk PDF
    html = f'''<html><head><meta charset="UTF-8"></head><body>
    <h2 style="text-align:center;">Form Collection Report</h2>
    <p><strong>User:</strong> {user}</p>
    <p><strong>Role:</strong> {role}</p>
    <table border="1" cellspacing="0" cellpadding="4">
    <tr><th>Company</th><th>Kontak</th><th>Tanggal</th><th>Waktu</th><th>Tujuan</th><th>Notes</th></tr>'''
    for k in filtered_data:
        html += f"<tr><td>{k.get('nama_company','')}</td><td>{k.get('nama_kontak','')}</td><td>{k.get('tanggal_kunjungan','')}</td><td>{k.get('waktu_kunjungan','')}</td><td>{k.get('tujuan_kunjungan','')}</td><td>{k.get('notes','')}</td></tr>"
    html += "</table></body></html>"
    result = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html), dest=result)
    if pisa_status.err:
        return 'Gagal membuat PDF', 500
    response = make_response(result.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=kunjungan_data.pdf'
    return response

# Halaman Logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
