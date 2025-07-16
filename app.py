# 🔧 Standard Library
import os
import re
import time
import hashlib
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 🧱 Third-party Libraries
import jwt
import numpy as np
from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, current_app as app
)
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson import json_util
from dotenv import load_dotenv
from pathlib import Path
from midtransclient import Snap
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

# === Load .env ===
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

# === Konfigurasi dari .env ===
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME")
SECRET_KEY = os.getenv("SECRET_KEY", "default-secret")
TOKEN_KEY = os.getenv("TOKEN_KEY", "default-token")
MIDTRANS_SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY")
MIDTRANS_CLIENT_KEY = os.getenv("MIDTRANS_CLIENT_KEY")

# === Inisialisasi Flask ===
app = Flask(__name__)

# === MongoDB ===
client = MongoClient(MONGODB_URI)
db = client[DB_NAME]

snap = Snap(
    is_production=False,
    server_key=MIDTRANS_SERVER_KEY,
    client_key=MIDTRANS_CLIENT_KEY
)

# === Logging ===
logging.basicConfig(level=logging.INFO)


@app.route('/')
def index():
    return render_template('index.html')


@app.route("/sendchat", methods=['POST'])
def send_chat():
    data = request.get_json()
    orderid = data.get('orderid')
    message = data.get('message')

    username = request.cookies.get('username')
    role = request.cookies.get('role')

    if not orderid or not message or not username:
        return jsonify({'result': 'error', 'message': 'Data tidak lengkap atau cookie tidak ditemukan'})

    now = datetime.now(ZoneInfo("Asia/Jakarta"))
    mytime_str = now.strftime('%Y-%m-%d %H:%M:%S')

    db.livechat.insert_one({
        'order_id': orderid,
        'username': username,
        'role': role,
        'message': message,
        'timestamp': mytime_str
    })

    return jsonify({'result': 'success'})


@app.route("/getchat")
def get_chat():
    orderid = request.args.get('orderid')
    if not orderid:
        return jsonify({'result': 'error', 'message': 'Order ID diperlukan'})

    order = db.orderan.find_one({'order_id': orderid})
    if not order:
        deleted = db.livechat.delete_many({'order_id': orderid})
        return jsonify({'result': 'error', 'message': f'Order tidak ditemukan. {deleted.deleted_count} chat telah dihapus.'})

    chat_cursor = db.livechat.find({'order_id': orderid}).sort('timestamp', 1)
    chat_list = [
        {
            'username': c['username'],
            'message': c['message'],
            'timestamp': c['timestamp'],
            'role': c['role']
        }
        for c in chat_cursor
    ]
    return jsonify({'result': 'success', 'chat': chat_list})


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/sign_in', methods=["POST"])
def sign_in():
    username_receive = request.form.get('username_give')
    password_receive = request.form.get('password_give')
    pw_hash = hashlib.sha256(password_receive.encode("utf-8")).hexdigest()

    user = db.login.find_one({"username": username_receive})

    if user:
        if user["password"] == pw_hash:
            payload = {'id': username_receive}
            token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
            return jsonify({
                "result": "success",
                "token": token,
                "role": user["role"],
                "username": user["username"]
            })
        else:
            return jsonify({
                "result": "fail",
                "msg": "Password yang Anda masukkan salah",
                "error": "password"
            })
    else:
        return jsonify({
            "result": "fail",
            "msg": "Username tidak ditemukan",
            "error": "username"
        })


@app.route('/check_id', methods=['POST'])
def check_id():
    username_receive = request.form['username_give']
    exists = bool(db.login.find_one({'username': username_receive}))
    return jsonify({'result': 'success', 'exists': exists})


@app.route('/check_judul', methods=['POST'])
def check_judul():
    judul_receive = request.form['judul_give']
    exists = bool(db.barang.find_one({'JudulBuku': judul_receive}))
    return jsonify({'result': 'success', 'exists': exists})


@app.route('/registuser')
def registuser():
    return render_template('regisuser.html')


@app.route('/ruser', methods=["POST"])
def ruser():
    email_receive = request.form.get('email')
    username_receive = request.form.get('username_give')
    password_receive = request.form.get('password_give')
    password_hash = hashlib.sha256(
        password_receive.encode('utf-8')).hexdigest()

    doc = {
        'email': email_receive,
        'username': username_receive,
        'password': password_hash,
        'nohp': '',
        'alamat': '',
        'profile_default': '/static/profil_default.jpg',
        'role': 'user'
    }
    db.login.insert_one(doc)
    return jsonify({'result': 'success'})


@app.route('/adminpage')
def adminpage():
    hapus_pesanan_kadaluarsa()
    return render_template('admin.html')


@app.route('/userpage')
def userpage():
    hapus_pesanan_kadaluarsa()
    return render_template('user.html')


def extract_public_id(cloudinary_url):
    try:
        if not cloudinary_url or "res.cloudinary.com" not in cloudinary_url:
            return None

        # Ambil bagian setelah '/upload/'
        path = cloudinary_url.split("/upload/")[-1]

        # Pisahkan path berdasarkan '/'
        segments = path.split('/')
        clean_segments = []

        for seg in segments:
            # Hilangkan transformasi dan versi
            if ',' in seg:  # Transformasi: f_auto,q_auto,...
                continue
            # Versi seperti v162234234
            if seg.startswith('v') and seg[1:].isdigit():
                continue
            clean_segments.append(seg)

        # Gabungkan ulang path
        full_path = '/'.join(clean_segments)

        # Hapus ekstensi file (contoh: .jpg, .webp, .npy)
        if '.' in full_path:
            full_path = '.'.join(full_path.split('.')[:-1])

        return full_path
    except Exception as e:
        print(f"Error ekstrak public_id: {e}")
        return None


@app.route('/deletebook', methods=['POST'])
def deletebook():
    judul = request.form.get('judul_give')
    buku = db.barang.find_one({"JudulBuku": judul}, {"_id": False})

    if not buku:
        return jsonify({'msg': 'Data tidak ditemukan!'})

    url = buku.get("URL")
    cover_old_list = buku.get("AllCover", [])

    # Gabungkan semua cover dari AllCover
    all_urls = set()
    if isinstance(cover_old_list, str):
        all_urls.add(cover_old_list)
    elif isinstance(cover_old_list, list):
        all_urls.update(cover_old_list)

    # Proses penghapusan Cloudinary
    for old_url in all_urls:
        public_id = extract_public_id(old_url)
        if public_id:
            try:
                result = cloudinary.uploader.destroy(
                    public_id, invalidate=True)
                print(f"Hapus {public_id} → {result}")
            except Exception as e:
                print(f"Gagal menghapus {public_id}: {e}")

    # Hapus data dari database
    db.barang.delete_one({'JudulBuku': judul})
    db.favorite.delete_many({'JudulBuku': url})
    db.cart.delete_many({'JudulBuku': url})

    return jsonify({
        'result': 'success',
        'msg': f'{judul} telah dihapus',
    })


@app.route('/cateringcuy')
def admin():
    return render_template('regisadmin.html')


@app.route('/radmin', methods=["POST"])
def radmin():
    email_receive = request.form.get('email')
    nomor_receive = request.form.get('nomor_give')
    username_receive = request.form.get('username_give')
    password_receive = request.form.get('password_give')
    password_hash = hashlib.sha256(
        password_receive.encode('utf-8')).hexdigest()

    doc = {
        'email': email_receive,
        'username': username_receive,
        'password': password_hash,
        'nohp': nomor_receive,
        'alamat': '',
        'profile_default': '/static/profil_default.jpg',
        'role': 'admin'
    }
    db.login.insert_one(doc)
    return jsonify({'result': 'success'})


@app.route('/hanyabarang')
def hanyabarang():
    book_list = list(db.barang.find({}, {'_id': False}))
    return jsonify({
        'daftarbuku': book_list
    })


@app.route('/barang')
def barang():
    user_receive = request.cookies.get("username")
    book_list = list(db.barang.find({}, {'_id': False}))
    favorite_list = list(db.favorite.find(
        {'username': user_receive}, {'_id': False}))
    cart_list = list(db.cart.find({'username': user_receive}, {'_id': False}))
    order_list = list(db.orderan.find({'username': user_receive}, {'_id': False}))

    return jsonify({
        'daftarbuku': book_list,
        'daftarfavorite': favorite_list,
        'daftarkeranjang': cart_list,
        'daftarorder': order_list
    })


@app.route('/dbadmin')
def dbadmin():
    user_receive = request.cookies.get("username")
    book_list = list(db.barang.find({}, {'_id': False}))
    user_list = list(db.login.find({'role': 'user'}, {'_id': False}))
    favorite_list = list(db.favorite.find(
        {'username': user_receive}, {'_id': False}))
    cart_list = list(db.cart.find({'username': user_receive}, {'_id': False}))
    order_list = list(db.orderan.find({}, {'_id': False}))
    pembatalan_list = list(db.pembatalan.find({}, {'_id': False}))

    return jsonify({
        'daftarbuku': book_list,
        'daftaruser': user_list,
        'daftarfavorite': favorite_list,
        'daftarkeranjang': cart_list,
        'daftarorder': order_list,
        'daftarpembatalan': pembatalan_list
    })


@app.route('/hapus-user', methods=['POST'])
def hapus_user():
    username = request.form.get('username_give')

    # Ambil data user
    user_data = db.login.find_one({'username': username})
    if not user_data:
        return jsonify({'msg': 'User tidak ditemukan.'}), 404

    # Hapus foto profil jika bukan default
    old_url = user_data.get("profile_default", "")
    if old_url and "res.cloudinary.com" in old_url and not old_url.startswith('/static/'):
        public_id = extract_public_id(old_url)
        if public_id:
            try:
                result = cloudinary.uploader.destroy(
                    public_id, invalidate=True)
                print(f"Hapus foto profil: {public_id} → {result}")
            except Exception as e:
                print(f"Gagal menghapus gambar profil Cloudinary: {e}")

    # Hapus user dari semua koleksi terkait
    db.login.delete_one({'username': username})
    db.cart.delete_many({'username': username})
    db.favorite.delete_many({'username': username})
    db.livechat.delete_many({'username': username})
    db.orderan.delete_many({'username': username})
    db.pembatalan.delete_many({'username': username})

    return jsonify({'msg': f'User {username} berhasil dihapus.'})


@app.route('/reset-password', methods=['POST'])
def reset_password():
    username = request.form.get('username_give')
    default_pw = hashlib.sha256('12345678'.encode()).hexdigest()
    db.login.update_one({'username': username}, {
                        '$set': {'password': default_pw}})
    return jsonify({'msg': f'Password user {username} berhasil direset ke 12345678.'})


@app.route('/tambah')
def tambah():
    return render_template('tambahitem.html')


@app.route("/tambahbuku", methods=["POST"])
def tambahbuku():
    judul_receive = request.form.get('judul_give')
    deskripsi_receive = request.form.get('deskripsi_give')
    harga_receive = int(request.form.get('harga_give'))
    stok_receive = int(request.form.get('stok_give'))
    kategori_receive = request.form.get('kategori_give')
    url_receive = request.form.get('url_give')

    today = datetime.now()
    mytime = today.strftime('%Y-%m-%d-%H-%M-%S')

    files = request.files.getlist("gambar_give[]")

    if not files or files[0].filename == "":
        return jsonify({'msg': 'Gambar tidak ditemukan!'})

    cover_list = []
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

    for index, file in enumerate(files):
        filename = secure_filename(file.filename)
        extension = filename.split(".")[-1].lower()

        if extension not in ['jpg', 'jpeg', 'png', 'webp']:
            return jsonify({'msg': f'File tidak valid: {filename}'})

        # ✅ Hanya gunakan nama tanpa prefix folder
        public_id = f"{url_receive}_{timestamp}_{index+1}"

        try:
            result = cloudinary.uploader.upload(
                file,
                folder="cover_buku",      # Folder ditentukan di sini
                public_id=public_id       # Tanpa "cover_buku/" di public_id
            )
        except Exception as e:
            return jsonify({'msg': f"Gagal upload {filename}: {str(e)}"}), 500

        # ✅ Optimized URL harus tambahkan prefix "cover_buku/" di sini saja
        optimized_url, _ = cloudinary_url(
            f"cover_buku/{public_id}",
            fetch_format="auto",
            quality="auto",
            secure=True
        )

        cover_list.append(optimized_url)

    cover_thumbnail = cover_list[0]

    doc = {
        'Date': mytime,
        'JudulBuku': judul_receive,
        'Deskripsi': deskripsi_receive,
        'Harga': harga_receive,
        'Stok': stok_receive,
        'Kategori': kategori_receive,
        'URL': url_receive,
        'Cover': cover_thumbnail,
        'AllCover': cover_list
    }

    db.barang.insert_one(doc)
    return jsonify({'msg': 'Inputan Berhasil!'})


@app.route("/profile")
def profile():
    token_receive = request.cookies.get(TOKEN_KEY)
    try:
        payload = jwt.decode(token_receive, SECRET_KEY, algorithms=["HS256"])
        username = payload.get('id')

        user_info = db.login.find_one({"username": username}, {"_id": False})

        # Ambil status verifikasi langsung dari db.login
        user_info["verifikasi_wajah"] = bool(
            user_info.get("verifikasi") == True)

        return render_template("profile.html", user_info=user_info)

    except (jwt.ExpiredSignatureError, jwt.exceptions.DecodeError):
        return redirect(url_for("login"))


@app.route('/update_profile', methods=["POST"])
def update_profile():
    token_receive = request.cookies.get(TOKEN_KEY)
    try:
        payload = jwt.decode(token_receive, SECRET_KEY, algorithms=["HS256"])
        username = payload.get("id")

        email_receive = request.form.get("email_give")
        nomor_receive = request.form.get("nomor_give")
        alamat_receive = request.form.get("alamat_give")

        now = datetime.now(ZoneInfo("Asia/Jakarta"))
        mytime = now.strftime('%Y%m%d%H%M%S')

        new_doc = {
            'email': email_receive,
            'nohp': nomor_receive,
            'alamat': alamat_receive
        }

        if "file_give" in request.files:
            file = request.files.get("file_give")
            filename = secure_filename(file.filename)
            extension = filename.split(".")[-1].lower()

            if extension not in ['jpg', 'jpeg', 'png', 'webp']:
                return jsonify({"result": "error", "msg": "Format gambar tidak didukung!"}), 400

            public_id = f"{username}_{mytime}"

            try:
                result = cloudinary.uploader.upload(
                    file,
                    folder="profile",
                    public_id=public_id,
                    transformation=[
                        {
                            "fetch_format": "auto",
                            "quality": "auto",
                            "width": 300,
                            "height": 300,
                            "crop": "fill",
                            "gravity": "face"
                        }
                    ]
                )

                optimized_url = result['secure_url']
                new_doc['profile_default'] = optimized_url

                # Hapus foto profil lama
                user_data = db.login.find_one({"username": username})
                old_url = user_data.get("profile_default", "")
                if old_url and "res.cloudinary.com" in old_url and not old_url.startswith("/static/"):
                    try:
                        public_id_old = extract_public_id(old_url)
                        if public_id_old:
                            result = cloudinary.uploader.destroy(
                                public_id_old, invalidate=True)
                            print(
                                f"Hapus foto profil lama: {public_id_old} → {result}")
                    except Exception as e:
                        print(f"Gagal menghapus gambar lama: {e}")
            except Exception as upload_err:
                return jsonify({"result": "error", "msg": f"Gagal upload foto: {str(upload_err)}"}), 500

        db.login.update_one({"username": username}, {"$set": new_doc})
        return jsonify({"result": "success", "msg": "Profil berhasil diperbarui!"})

    except (jwt.ExpiredSignatureError, jwt.exceptions.DecodeError):
        return redirect(url_for("/"))


@app.route('/favorite')
def favorite():
    return render_template('favorite.html')


@app.route('/showfav')
def showfav():
    user_receive = request.cookies.get("username")
    favorite_list = list(db.favorite.find(
        {'username': user_receive}, {'_id': False}))
    cart_list = list(db.cart.find({'username': user_receive}, {'_id': False}))
    book_list = []
    for i in favorite_list:
        judulfav = i["JudulBuku"]
        book_find = db.barang.find_one({"URL": judulfav}, {"_id": False})
        book_list.append(book_find)
    return jsonify({'daftarbuku': book_list, 'daftarfavorite': favorite_list, 'daftarkeranjang': cart_list})


@app.route('/fav', methods=["POST"])
def fav():
    judul_receive = request.form.get('judul_give')
    username_receive = request.form.get('username_give')
    action_receive = request.form.get('action_give')
    doc = {
        'JudulBuku': judul_receive,
        'username': username_receive,
        'status': 'favorited'
    }
    if action_receive == "favorited":
        db.favorite.insert_one(doc)
        return jsonify({'result': 'success', 'msg': action_receive})
    else:
        db.favorite.delete_one(doc)
        return jsonify({'result': 'success', 'msg': "terhapus dari favorite"})


@app.route('/cart')
def cart():
    return render_template('cart.html')


@app.route('/showcart')
def showcart():
    user_receive = request.cookies.get("username")
    cart_list = list(db.cart.find({'username': user_receive}, {'_id': False}))

    book_list = []

    for item in cart_list:
        judul_fav = item.get("JudulBuku")
        book_data = db.barang.find_one({"URL": judul_fav}, {"_id": False})

        if book_data:
            # Validasi & konversi stok ke integer
            try:
                stok = int(book_data.get('Stok', 0))
            except (ValueError, TypeError):
                stok = 0

            if stok > 0:
                # Gabungkan data keranjang dan buku (jika perlu)
                merged_data = item.copy()
                merged_data.update(book_data)
                book_list.append(merged_data)

    return jsonify({
        'daftarbuku': book_list,         # hanya yang stoknya > 0
        'daftarkeranjang': cart_list     # semua keranjang user
    })


@app.route('/addcart', methods=["POST"])
def addcart():
    judul_receive = request.form.get('judul_give')
    username_receive = request.form.get('username_give')
    action_receive = request.form.get('action_give')
    doc = {
        'JudulBuku': judul_receive,
        'username': username_receive,
        'status': 'dalam keranjang'
    }
    if action_receive == "Added to cart":
        db.cart.insert_one(doc)
        return jsonify({'result': 'success', 'msg': action_receive})
    else:
        db.cart.delete_one(doc)
        return jsonify({'result': 'success', 'msg': "terhapus dari keranjang"})


@app.route('/orderan', methods=['POST'])
def orderan():
    data = request.get_json()

    username_receive = data.get('username_give')
    pesanan_receive = data.get('pesanan_give')  # list of dicts

    if not username_receive or not pesanan_receive:
        return jsonify({'result': 'error', 'msg': 'Data tidak lengkap'}), 400

    order_id = f"ORDER-{username_receive}-{int(time.time())}"

    # Ambil waktu lokal (WIB)
    now_jakarta = datetime.now(ZoneInfo("Asia/Jakarta"))

    # Ubah ke UTC
    now_utc = datetime.now(ZoneInfo("UTC"))

    # Simpan format string (jika perlu untuk tampilan)
    mytime_str = now_jakarta.strftime('%Y-%m-%d %H:%M:%S')

    items_to_save = []

    for item in pesanan_receive:
        judul = item.get('judul')
        jumlah = int(item.get('jumlah', 0))
        harga = int(item.get('harga', 0))

        if not judul or jumlah <= 0 or harga <= 0:
            continue  # Skip jika data tidak valid

        # Ambil cover dan AllCover dari koleksi barang
        book = db.barang.find_one({'JudulBuku': judul}, {
            '_id': False, 'Cover': True, 'AllCover': True})
        cover = book.get('Cover', '') if book else ''
        all_cover = book.get('AllCover', []) if book else []

        item.update({
            'order_id': order_id,
            'username': username_receive,
            'tanggal': mytime_str,
            'cover': cover,
            'AllCover': all_cover,
            'status': 'Belum Bayar',
            'waktu': now_utc
        })

        items_to_save.append(item)

        # Kurangi stok buku
        db.barang.update_one({'JudulBuku': judul}, {'$inc': {'Stok': -jumlah}})

    if not items_to_save:
        return jsonify({'result': 'error', 'msg': 'Tidak ada item valid untuk disimpan'}), 400

    # Simpan semua item ke database
    db.orderan.insert_many(items_to_save)

    # Kosongkan keranjang user
    db.cart.delete_many({'username': username_receive})

    return jsonify({
        'result': 'success',
        'msg': "Orderan diterima",
        'order_id': order_id,
        'jumlah_item': len(items_to_save)
    })


@app.route('/bayar', methods=['POST'])
def bayar():
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        order_id = data.get('order_id')
        tanggal_str = data.get('tanggal_give')

        if not order_id or not tanggal_str:
            return jsonify({"result": "error", "message": "Order ID dan tanggal wajib diisi."}), 400

        orders = list(db.orderan.find({'order_id': order_id}))

        if not orders:
            return jsonify({"result": "error", "message": "Order tidak ditemukan."}), 404

        existing_token = orders[0].get('snap_token')
        status_order = orders[0].get('status')

        # Jika transaksi sudah lunas
        if status_order == 'Sudah Bayar':
            return jsonify({
                "result": "success",
                "order_id": order_id,
                "msg": "Transaksi ini sudah lunas. Tidak perlu bayar lagi."
            })

        # Jika sudah punya snap token, kirim token lama
        if existing_token:
            return jsonify({
                "result": "success",
                "snap_token": existing_token,
                "order_id": order_id,
                "msg": "Silakan lanjutkan ke pembayaran sebelumnya"
            })

        # Buat Snap Token baru
        try:
            waktu_obj = datetime.strptime(
                tanggal_str, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=ZoneInfo("Asia/Jakarta"))
            start_time = waktu_obj.strftime("%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            return jsonify({"result": "error", "message": "Format tanggal tidak valid."}), 400

        total = sum(int(item.get('harga', 0)) for item in orders)
        username = orders[0].get('username', 'User')

        transaction = {
            "transaction_details": {
                "order_id": order_id,
                "gross_amount": total
            },
            "customer_details": {
                "first_name": username,
                "email": f"{username}@example.com"
            },
            "expiry": {
                "start_time": start_time,
                "unit": "hour",
                "duration": 24
            }
        }

        response = snap.create_transaction(transaction)
        snap_token = response.get('token')

        if not snap_token:
            raise Exception("Gagal mendapatkan Snap Token dari Midtrans.")

        # Simpan token saja, tanpa status
        db.orderan.update_many(
            {'order_id': order_id},
            {'$set': {'snap_token': snap_token}}
        )

        return jsonify({
            "result": "success",
            "snap_token": snap_token,
            "order_id": order_id,
            "msg": "Silakan lanjutkan ke pembayaran"
        })

    except Exception as e:
        logging.exception("Gagal memproses pembayaran:")
        return jsonify({
            "result": "error",
            "message": f"Terjadi kesalahan server: {str(e)}"
        }), 500


@app.route('/payment-callback', methods=['POST'])
def payment_callback():
    try:
        notification = request.get_json()
        transaction_status = notification.get('transaction_status')
        order_id = notification.get('order_id')
        status_message = notification.get('status_message', '')
        payment_type = notification.get('payment_type', '')
        fraud_status = notification.get('fraud_status', '')

        if not order_id:
            return jsonify({'message': 'Order ID tidak ditemukan'}), 400

        # Status default
        status = "Diproses"

        # Mapping status Midtrans → status internal
        if transaction_status in ['settlement', 'capture']:
            status = "Sudah Bayar"
        elif transaction_status in ['cancel', 'deny', 'expire']:
            status = "Dibatalkan"
        elif transaction_status == 'pending':
            status = "Menunggu Pembayaran"
        else:
            status = "Sudah Bayar"

        update_fields = {
            'status': status,
            'transaction_status': transaction_status,
            'payment_type': payment_type,
            'status_message': status_message,
            'fraud_status': fraud_status
        }

        # Jika pembayaran final (lunas atau batal), hapus snap_token
        if status in ['Sudah Bayar', 'Dibatalkan']:
            update_fields['snap_token'] = None

        db.orderan.update_many(
            {'order_id': order_id},
            {'$set': update_fields}
        )

        return jsonify({'message': f'Status pembayaran diperbarui ke: {status}'}), 200

    except Exception as e:
        logging.exception("Gagal memproses notifikasi Midtrans:")
        return jsonify({'message': 'Terjadi kesalahan pada server'}), 500


@app.route('/orders')
def orders():
    hapus_pesanan_kadaluarsa()
    return render_template('pesanan.html')


@app.route('/orderadmin')
def orderadmin():
    hapus_pesanan_kadaluarsa()
    return render_template('orderadmin.html')


@app.route('/konfirmasi_pembatalan', methods=['POST'])
def konfirmasi_pembatalan():
    data = request.get_json()
    orderid = data.get('order_id')
    username = data.get('username')

    if not orderid or not username:
        return jsonify({'result': 'error', 'message': 'Data tidak lengkap'})

    # Hapus dari koleksi pembatalan
    db.pembatalan.delete_many({'order_id': orderid})

    # Update status di orderan
    result = db.orderan.update_many(
        {'order_id': orderid},
        {'$set': {'status': 'Dibatalkan'}}
    )

    return jsonify({'result': 'success', 'updated': result.modified_count})


@app.route('/kirim_pesanan', methods=['POST'])
def kirim_pesanan():
    data = request.get_json()
    orderid = data.get('order_id')
    username = data.get('username')

    if not orderid or not username:
        return jsonify({'result': 'error', 'message': 'Data tidak lengkap'})

    result = db.orderan.update_many(
        {'order_id': orderid},
        {'$set': {'status': 'Terkirim'}}
    )

    return jsonify({'result': 'success', 'updated': result.modified_count})


@app.route('/showorder')
def showorder():
    user_receive = request.cookies.get("username")
    now = datetime.now(ZoneInfo("Asia/Jakarta"))

    order_list = list(db.orderan.find(
        {'username': user_receive}, {'_id': False}))

    orders_list = []

    for order in order_list:
        tanggal_str = order.get('tanggal')  # string: "2025-06-23 23:22:06"

        try:
            order_time = datetime.strptime(
                tanggal_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Jakarta"))
        except:
            order_time = now  # fallback jika parsing gagal

        # Hapus jika lebih dari 1 hari dan status belum bayar
        if order.get('status', '').lower() == 'belum bayar' and now - order_time > timedelta(days=1):
            judul = order.get('judul') or order.get('judul')
            jumlah = int(order.get('jumlah') or order.get('jumlah', 0))

            if judul and jumlah > 0:
                db.barang.update_one(
                    {'JudulBuku': judul},
                    {'$inc': {'Stok': jumlah}}
                )

            db.orderan.delete_one({'order_id': order['order_id']})
            continue

        # Cek status pembatalan jika ada
        pembatalan = db.pembatalan.find_one(
            {'order_id': order['order_id']}, {'_id': False})
        order['status_pembatalan'] = pembatalan.get(
            'status', 'diajukan') if pembatalan else None

        orders_list.append(order)

    return jsonify({'daftarorderan': orders_list, 'daftarorder': orders_list})


@app.route('/pesanan-selesai', methods=['POST'])
def pesanan_selesai():
    data = request.get_json()
    orderid = data.get('orderid')

    if not orderid:
        return jsonify({'result': 'error', 'message': 'Order ID tidak ditemukan'})

    result = db.orderan.update_many(
        {'order_id': orderid},
        {'$set': {'status': 'Pesanan Selesai'}}
    )

    if result.modified_count > 0:
        return jsonify({'result': 'success'})
    else:
        return jsonify({'result': 'error', 'message': 'Tidak ada data yang diubah'})


@app.route('/hapus-pesanan', methods=['POST'])
def hapus_pesanan():
    # Ambil token dari body POST (bukan cookie)
    token_receive = request.form.get('token')
    print("token_receive:", token_receive)

    if not token_receive:
        return jsonify({
            'result': 'unauthorized',
            'msg': 'Token tidak dikirim di body request'
        }), 401

    try:
        payload = jwt.decode(token_receive, SECRET_KEY, algorithms=["HS256"])
        username = payload.get('id')
        print("username dari token:", username)
    except jwt.ExpiredSignatureError:
        return jsonify({
            'result': 'unauthorized',
            'msg': 'Token kadaluarsa'
        }), 401
    except jwt.exceptions.DecodeError:
        return jsonify({
            'result': 'unauthorized',
            'msg': 'Token tidak valid'
        }), 401

    order_id = request.form.get('order_id')
    if not order_id:
        return jsonify({
            'result': 'error',
            'msg': 'Order ID tidak diberikan'
        }), 400

    # Cari semua item pesanan
    items = list(db.orderan.find({'order_id': order_id}))
    if not items:
        return jsonify({
            'result': 'error',
            'msg': 'Pesanan tidak ditemukan'
        }), 404

    pemilik = items[0].get('username')
    if pemilik != username:
        return jsonify({
            'result': 'forbidden',
            'msg': 'Anda tidak berhak menghapus pesanan ini'
        }), 403

    # Kembalikan stok barang
    for item in items:
        judul = item.get('judul')
        jumlah = int(item.get('jumlah', 0))
        if judul and jumlah > 0:
            db.barang.update_one(
                {'JudulBuku': judul},
                {'$inc': {'Stok': jumlah}}
            )
            print(f"Stok dikembalikan: {judul} +{jumlah}")

    # Hapus dari semua koleksi terkait
    hasil_orderan = db.orderan.delete_many({'order_id': order_id})
    hasil_pembatalan = db.pembatalan.delete_many({'order_id': order_id})
    hasil_livechat = db.livechat.delete_many({'order_id': order_id})

    return jsonify({
        'result': 'success',
        'msg': f"Pesanan dihapus ({hasil_orderan.deleted_count} item), stok dikembalikan",
        'pembatalan_dihapus': hasil_pembatalan.deleted_count,
        'livechat_dihapus': hasil_livechat.deleted_count
    })


@app.route("/batal-pembatalan", methods=["POST"])
def batal_pembatalan():
    order_id = request.form.get("order_id")
    db.pembatalan.delete_one({"order_id": order_id})
    return jsonify({"msg": "Permintaan pembatalan dibatalkan"})


@app.route('/detail/<book>')
def detail(book):
    book_detail = db.barang.find_one({"URL": book}, {"_id": False})
    return render_template('detail.html', book_detail=book_detail)


@app.route('/edit/<book>')
def editbook(book):
    book_edit = db.barang.find_one({"URL": book}, {"_id": False})
    return render_template('editbook.html', book_edit=book_edit)


@app.route("/editcover", methods=["POST"])
def editcover():
    barang = request.form.get('judul_give')
    databarang = db.barang.find_one({"JudulBuku": barang}, {"_id": False})

    if not databarang:
        return jsonify({'msg': 'Data tidak ditemukan!'})

    # Dapatkan daftar cover lama
    cover_old_list = databarang.get("AllCover", [])
    if isinstance(cover_old_list, str):
        cover_old_list = [cover_old_list]

    # Hapus cover lama dari Cloudinary
    for old_url in cover_old_list:
        if old_url and "res.cloudinary.com" in old_url:
            public_id = extract_public_id(old_url)
            if public_id:
                try:
                    result = cloudinary.uploader.destroy(public_id)
                    print(f"Hapus cover lama: {public_id} → {result}")
                except Exception as e:
                    print(f"Gagal menghapus cover lama: {e}")

    # Ambil file cover baru
    files = request.files.getlist("gambar_give[]")
    if not files or files[0].filename == "":
        return jsonify({'msg': 'Gambar tidak ditemukan!'})

    cover_list = []
    url_receive = databarang["URL"]
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

    for index, file in enumerate(files):
        filename = secure_filename(file.filename)
        extension = filename.split(".")[-1].lower()

        if extension not in ['jpg', 'jpeg', 'png', 'webp']:
            return jsonify({'msg': f'File tidak valid: {filename}'})

        # ✅ Gunakan public_id TANPA "cover_buku/"
        public_id = f"{url_receive}_{timestamp}_{index+1}"

        result = cloudinary.uploader.upload(
            file,
            public_id=public_id,
            folder="cover_buku"  # Sudah mengatur foldernya di sini
        )

        optimized_url, _ = cloudinary_url(
            f"cover_buku/{public_id}",  # ✅ Tambahkan prefix DI SINI saja
            fetch_format="auto",
            quality="auto"
        )
        cover_list.append(optimized_url)

    # Update dokumen di database
    new_doc = {
        "AllCover": cover_list,
        "Cover": cover_list[0]
    }
    db.barang.update_one({"JudulBuku": barang}, {"$set": new_doc})
    return jsonify({'msg': 'Update Cover Berhasil!'})


@app.route("/editbuku", methods=["POST"])
def editbuku():
    try:
        update_deskripsi = request.form.get('deskripsi_update', '').strip()
        update_harga = int(request.form.get('harga_update', '0').strip())
        update_stok = int(request.form.get('stok_update', '0').strip())
        update_kategori = request.form.get('kategori_update', '').strip()
        judul = request.form.get('judul_give', '').strip()

        if not all([judul, update_deskripsi, update_kategori]):
            return jsonify({'msg': 'Data tidak lengkap!'}), 400

        new_doc = {
            'Deskripsi': update_deskripsi,
            'Harga': update_harga,
            'Stok': update_stok,
            'Kategori': update_kategori,
        }

        result = db.barang.update_one({"JudulBuku": judul}, {"$set": new_doc})

        if result.matched_count == 0:
            return jsonify({'msg': 'Buku tidak ditemukan!'}), 404

        return jsonify({'msg': 'Update Detail Berhasil!'})
    except Exception as e:
        print(f"Error saat mengupdate buku: {e}")
        return jsonify({'msg': 'Terjadi kesalahan di server'}), 500


@app.route('/search/<kata>')
def search(kata):
    try:
        pola_regex = re.compile(f".*{kata}.*", re.IGNORECASE)
        hasil = list(db.barang.find(
            {"JudulBuku": {"$regex": pola_regex}}, {"_id": False}))
        for item in hasil:
            harga = item.get("Harga", 0)
            if isinstance(harga, (int, float)):
                item["HargaFormat"] = f"Rp.{harga:,.0f}".replace(",", ".")
            else:
                item["HargaFormat"] = "Rp.0"

        aqua = json_util.loads(json_util.dumps(hasil))

        # Ambil username dari cookie
        username = request.cookies.get('username')

        # Ambil data favorite dan cart
        daftarfav = db.favorite.find({'username': username}, {'_id': False})
        daftarfavorite = [fav['JudulBuku'] for fav in daftarfav]

        daftarcart = db.cart.find({'username': username}, {'_id': False})
        daftarkeranjang = [cart['JudulBuku'] for cart in daftarcart]

        return render_template(
            'search.html',
            hasil=aqua,
            kata=kata,
            daftarfavorite=daftarfavorite,
            daftarkeranjang=daftarkeranjang
        )

    except (jwt.ExpiredSignatureError, jwt.exceptions.DecodeError):
        return redirect(url_for("/"))


@app.route("/ajukan-pembatalan", methods=["POST"])
def ajukan_pembatalan():
    try:
        id_receive = request.form["id_give"]
        username = request.form["username_give"]

        order = db.orderan.find_one({'order_id': id_receive})

        if not order:
            return jsonify({"msg": "Pesanan tidak ditemukan."})

        # Cek jika sudah diajukan pembatalan sebelumnya
        existing = db.pembatalan.find_one({"order_id": id_receive})
        if existing:
            return jsonify({"msg": "Pembatalan sudah diajukan sebelumnya."})

        db.pembatalan.insert_one({
            "order_id": id_receive,
            "username": username,
            "status": "diajukan",  # bisa juga 'pending'
            "waktu": datetime.now(ZoneInfo("Asia/Jakarta"))
        })

        return jsonify({"msg": "Pembatalan berhasil diajukan ke admin."})
    except Exception as e:
        print(e)
        return jsonify({"msg": "Terjadi kesalahan saat mengajukan pembatalan."})


def hapus_pesanan_kadaluarsa():
    """
    Hapus pesanan 'belum bayar' atau 'menunggu pembayaran' yang kadaluarsa >24 jam.
    """
    try:
        print("🔍 Menjalankan pengecekan pesanan kadaluarsa...")

        batas_waktu = datetime.now(ZoneInfo("UTC")) - timedelta(hours=24)
        hasil = db.orderan.delete_many({
            "status": {"$in": ["Belum Bayar", "Menunggu Pembayaran"]},
            "waktu": {"$lt": batas_waktu}
        })
        if hasil.deleted_count > 0:
            print(f"⏳ Hapus otomatis {hasil.deleted_count} pesanan kadaluarsa")
    except Exception as e:
        print("❌ Gagal hapus pesanan kadaluarsa:", e)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
