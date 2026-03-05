import httpx
import time
import re
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import json
from flask import Flask, request, jsonify
from datetime import datetime
import data_pb2
import encode_id_clan_pb2
import reqClan_pb2
import jwt as pyjwt

app = Flask(__name__)
freefire_version = "OB52"
key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
iv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

JWT_REGEX = re.compile(r'(eyJ[A-Za-z0-9_\-\.=]+)')

def get_jwt_token_from_api(uid, password):
    data_param = f"{uid}:{password}"
    url = f"https://api.freefireservice.dnc.su/oauth/account:login?data={data_param}"
    
    try:
        response = httpx.get(url, timeout=15.0)
        token_candidate = None
        
        try:
            j = response.json()
            for k in ("token", "jwt", "access_token", "data", "auth"):
                v = j.get(k)
                if isinstance(v, str) and v.startswith("ey"):
                    token_candidate = v
                    break
        except Exception:
            pass
        
        if not token_candidate:
            m = JWT_REGEX.search(response.text)
            if m:
                token_candidate = m.group(1)
        
        if not token_candidate:
            for hv in response.headers.values():
                m = JWT_REGEX.search(hv)
                if m:
                    token_candidate = m.group(1)
                    break
        
        return token_candidate
            
    except Exception as e:
        print(f"JWT Token API Error: {e}")
        return None

def get_region_from_jwt(jwt_token):
    try:
        decoded = pyjwt.decode(jwt_token, options={"verify_signature": False})
        lock_region = decoded.get('lock_region', 'BR')
        return lock_region.upper()
    except Exception as e:
        print(f"Region decode error: {e}")
        return 'BR'

def get_region_url(region):
    region = region.upper()
    if region == "BR":
        return "https://client.us.freefiremobile.com"
    elif region in ["BR", "US", "SAC", "NA"]:
        return "https://client.us.freefiremobile.com/"
    else:
        return "https://clientbp.ggblueshark.com/"

def create_join_payload(clan_id):
    message = reqClan_pb2.MyMessage()
    message.field_1 = int(clan_id)
    serialized_data = message.SerializeToString()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted_data = cipher.encrypt(pad(serialized_data, AES.block_size))
    return encrypted_data

def get_clan_info(base_url, jwt_token, clan_id):
    try:
        json_data = json.dumps({"1": int(clan_id), "2": 1})
        my_data = encode_id_clan_pb2.MyData()
        json_obj = json.loads(json_data)
        my_data.field1 = json_obj["1"]
        my_data.field2 = json_obj["2"]

        data_bytes = my_data.SerializeToString()
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted_info_data = cipher.encrypt(pad(data_bytes, 16))

        info_url = f"{base_url}/GetClanInfoByClanID"
        
        headers = {
            "Expect": "100-continue",
            "Authorization": f"Bearer {jwt_token}",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": freefire_version,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
            "Host": base_url.replace("https://", ""),
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }

        with httpx.Client(timeout=30.0) as client_info:
            info_response = client_info.post(info_url, headers=headers, content=encrypted_info_data)
        
        if info_response.status_code == 200:
            resp_info = data_pb2.response()
            resp_info.ParseFromString(info_response.content)
            return {
                "clan_name": getattr(resp_info, "special_code", "Unknown"),
                "clan_level": getattr(resp_info, "level", "Unknown")
            }
        else:
            return {"clan_name": "Unknown", "clan_level": "Unknown"}
    except Exception as e:
        print(f"Clan info error: {e}")
        return {"clan_name": "Unknown", "clan_level": "Unknown"}

@app.route('/join', methods=['GET'])
def join_clan():
    clan_id = request.args.get('clan_id')
    jwt_token = request.args.get('jwt')
    uid = request.args.get('uid')
    password = request.args.get('password')

    if not clan_id:
        return jsonify({
            "error": "clan_id is required"
        }), 400

    final_token = jwt_token
    
    if uid and password and not final_token:
        final_token = get_jwt_token_from_api(uid, password)
        if not final_token:
            return jsonify({
                "error": "Failed to get JWT token from uid/password"
            }), 400

    if not final_token:
        return jsonify({
            "error": "Either jwt token or uid/password is required"
        }), 400

    final_region = get_region_from_jwt(final_token)

    try:
        base_url = get_region_url(final_region)
        url = f"{base_url}/RequestJoinClan"
        host = base_url.replace("https://", "")

        encrypted_data = create_join_payload(clan_id)

        headers = {
            "Expect": "100-continue",
            "Authorization": f"Bearer {final_token}",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": freefire_version,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
            "Host": host,
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, content=encrypted_data)

        clan_info = get_clan_info(base_url, final_token, clan_id)

        if response.status_code == 200:
            result = {
                "clan_id": clan_id,
                "region": final_region,
                "clan_name": clan_info.get("clan_name", "Unknown"),
                "clan_level": clan_info.get("clan_level", "Unknown"),
                "message": "Request sent successfully",
                "status_code": response.status_code,
                "timestamp": time.time(),
                "success": True
            }
        else:
            result = {
                "clan_id": clan_id,
                "region": final_region,
                "clan_name": clan_info.get("clan_name", "Unknown"),
                "message": f"Failed with status {response.status_code}",
                "status_code": response.status_code,
                "timestamp": time.time(),
                "success": False
            }

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "error": "Server error",
            "details": str(e)
        }), 500

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Starting Clan Join API on port {port} ...")
    app.run(host='0.0.0.0', port=port, debug=False)
