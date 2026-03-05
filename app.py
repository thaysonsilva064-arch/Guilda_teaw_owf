import httpx
import time
import re
import json
import binascii
import requests
import urllib3
import jwt as pyjwt # Usado para decode de região
import jwt           # Usado no script 1
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import sys
import os

# Importação dos Protobufs
try:
    import data_pb2
    import encode_id_clan_pb2
    import reqClan_pb2
    import my_pb2
    import output_pb2
except ImportError as e:
    print(f"Erro ao importar Protobufs: {e}")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# --- CONFIGURAÇÕES E CHAVES ---
freefire_version = "OB52"
CLAN_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
CLAN_IV = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
MAJOR_KEY = b'Yg&tc%DEuh6%Zc^8'
MAJOR_IV = b'6oyZDr22E3ychjM%'
JWT_REGEX = re.compile(r'(eyJ[A-Za-z0-9_\-\.=]+)')

# --- FUNÇÕES AUXILIARES DE CRIPTOGRAFIA ---
def encrypt_clan(plaintext):
    cipher = AES.new(CLAN_KEY, AES.MODE_CBC, CLAN_IV)
    return cipher.encrypt(pad(plaintext, AES.block_size))

def encrypt_major(plaintext):
    cipher = AES.new(MAJOR_KEY, AES.MODE_CBC, MAJOR_IV)
    return cipher.encrypt(pad(plaintext, AES.block_size))

# --- FUNÇÕES DO SCRIPT 1 ---
def fetch_open_id(access_token):
    try:
        uid_url = "https://prod-api.reward.ff.garena.com/redemption/api/auth/inspect_token/"
        uid_headers = {"access-token": access_token, "user-agent": "Mozilla/5.0"}
        uid_res = requests.get(uid_url, headers=uid_headers, verify=False, timeout=10)
        uid = uid_res.json().get("uid")
        if not uid: return None, "Failed to extract UID"
        openid_url = "https://topup.pk/api/auth/player_id_login"
        payload = {"app_id": 100067, "login_id": str(uid)}
        openid_res = requests.post(openid_url, json=payload, verify=False, timeout=10)
        return openid_res.json().get("open_id"), None
    except Exception as e: return None, str(e)

def convert_access_to_jwt(access_token, provided_open_id=None):
    open_id = provided_open_id or fetch_open_id(access_token)[0]
    if not open_id: return None
    platforms = [8, 3, 4, 6]
    for p_type in platforms:
        game_data = my_pb2.GameData()
        game_data.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        game_data.game_name = "free fire"
        game_data.open_id = str(open_id)
        game_data.access_token = access_token
        game_data.platform_type = p_type
        enc_data = encrypt_major(game_data.SerializeToString())
        url = "https://loginbp.ggblueshark.com/MajorLogin"
        headers = {"Content-Type": "application/octet-stream", "ReleaseVersion": "OB52"}
        try:
            resp = requests.post(url, data=enc_data, headers=headers, verify=False, timeout=5)
            if resp.status_code == 200:
                msg = output_pb2.Garena_420()
                msg.ParseFromString(resp.content)
                if getattr(msg, "token", None): return msg.token
        except: continue
    return None

# --- FUNÇÕES DO SCRIPT 2 (CLAN) ---
def get_jwt_token_from_api(uid, password):
    url = f"https://api.freefireservice.dnc.su/oauth/account:login?data={uid}:{password}"
    try:
        response = httpx.get(url, timeout=15.0)
        m = JWT_REGEX.search(response.text)
        return m.group(1) if m else None
    except: return None

def get_region_from_jwt(jwt_token):
    try:
        decoded = pyjwt.decode(jwt_token, options={"verify_signature": False})
        return decoded.get('lock_region', 'BR').upper()
    except: return 'IND'

def get_region_url(region):
    if region.upper() in ["BR", "US", "SAC", "NA"]: return "https://client.us.freefiremobile.com"
    return "https://clientbp.ggblueshark.com/"

def get_clan_info(base_url, jwt_token, clan_id):
    try:
        my_data = encode_id_clan_pb2.MyData()
        my_data.field1 = int(clan_id)
        my_data.field2 = 1
        enc_info = AES.new(CLAN_KEY, AES.MODE_CBC, CLAN_IV).encrypt(pad(my_data.SerializeToString(), 16))
        headers = {"Authorization": f"Bearer {jwt_token}", "ReleaseVersion": freefire_version, "Content-Type": "application/octet-stream"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{base_url}/GetClanInfoByClanID", headers=headers, content=enc_info)
        if resp.status_code == 200:
            resp_info = data_pb2.response()
            resp_info.ParseFromString(resp.content)
            return {"clan_name": getattr(resp_info, "special_code", "Unknown"), "clan_level": getattr(resp_info, "level", "Unknown")}
    except: pass
    return {"clan_name": "Unknown", "clan_level": "Unknown"}

# --- ROTAS ---
@app.route('/')
def read_root():
    return '<h1 style="text-align:center;">API Integrada Clan + Login FF Running!</h1>'

@app.route('/join', methods=['GET'])
def join_clan():
    clan_id = request.args.get('clan_id')
    jwt_token = request.args.get('jwt')
    access_token = request.args.get('access_token')
    provided_open_id = request.args.get('open_id')
    uid, password = request.args.get('uid'), request.args.get('password')

    if not clan_id: return jsonify({"error": "clan_id is required"}), 400

    final_token = jwt_token or (convert_access_to_jwt(access_token, provided_open_id) if access_token else get_jwt_token_from_api(uid, password) if uid else None)
    if not final_token: return jsonify({"error": "Auth failed"}), 400

    final_region = get_region_from_jwt(final_token)
    try:
        base_url = get_region_url(final_region)
        encrypted_data = encrypt_clan(reqClan_pb2.MyMessage(field_1=int(clan_id)).SerializeToString())
        headers = {"Authorization": f"Bearer {final_token}", "ReleaseVersion": freefire_version, "Content-Type": "application/octet-stream"}
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{base_url}/RequestJoinClan", headers=headers, content=encrypted_data)
        clan_info = get_clan_info(base_url, final_token, clan_id)
        return jsonify({"clan_id": clan_id, "region": final_region, "clan_name": clan_info.get("clan_name"), "success": response.status_code == 200})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/access-jwt', methods=['GET'])
def majorlogin_jwt():
    access_token, open_id = request.args.get('access_token'), request.args.get('open_id')
    if not access_token: return jsonify({"message": "missing access_token"}), 400
    token = convert_access_to_jwt(access_token, open_id)
    return jsonify({"status": "success", "token": token}) if token else jsonify({"message": "failed"}), 400

# PARA O VERCEL: O app deve ser exportado assim
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
