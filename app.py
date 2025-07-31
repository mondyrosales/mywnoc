from flask import Flask, render_template, request, jsonify
import subprocess
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
import json
import os

# ---------------- JSON Data Handling ----------------
STORES_FILE = 'stores_list.json'

def load_stores():
    if not os.path.exists(STORES_FILE):
        with open(STORES_FILE, 'w') as f:
            json.dump({}, f)
    with open(STORES_FILE, 'r') as f:
        return json.load(f)

def save_stores(data):
    with open(STORES_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# Initialize store data
stores = load_stores()

# ---------------- Flask & Status Initialization ----------------
app = Flask(__name__)
status_data = {store: {"ip": ip, "status": "UNKNOWN", "latency": []} for store, ip in stores.items()}
previous_status = {store: "UNKNOWN" for store in stores}
last_check = None


def ping_gateway(ip, attempts=2, timeout=1500):
    success = 0
    latencies = []

    for _ in range(attempts):
        try:
            result = subprocess.run(
                ["ping", "-n", "5", "-w", str(timeout), ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if "TTL=" in result.stdout:
                success += 1
                for line in result.stdout.splitlines():
                    if "time=" in line:
                        try:
                            latency_str = line.split("time=")[-1].split("ms")[0].strip()
                            latencies.append(int(latency_str))
                        except ValueError:
                            pass
        except Exception:
            pass

        time.sleep(0.2)

    if success == 0:
        return ("DOWN", 0)

    avg_latency = sum(latencies) // len(latencies) if latencies else 0
    return ("UP", avg_latency)

def update_status():
    global last_check
    while True:
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = {store: executor.submit(ping_gateway, data["ip"]) for store, data in status_data.items()}
        for store, future in futures.items():
            new_status, latency = future.result()
            if new_status == "DOWN" and previous_status[store] == "UP":
                confirm, latency = ping_gateway(status_data[store]["ip"], attempts=3)
                new_status = confirm
            previous_status[store] = new_status
            status_data[store]["status"] = new_status
            status_data[store]["latency"].append(latency)
            if len(status_data[store]["latency"]) > 30:
                status_data[store]["latency"] = status_data[store]["latency"][1:]
        last_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(1)

# HTML Template with dynamic chart sizing and working add/edit functionality
@app.route('/')
def index():
    return render_template('dashboard.html')

# ---------------- Flask Routes ----------------
@app.route('/status')
def get_status():
    return jsonify({"status": status_data, "last_check": last_check})

@app.route('/edit', methods=['POST'])
def edit_device():
    data = request.json
    old_name = data['old_name']
    new_name = data['new_name']
    new_ip = data['new_ip']
    if old_name in status_data:
        # Update status and previous
        status_data[new_name] = status_data.pop(old_name)
        status_data[new_name]['ip'] = new_ip
        previous_status[new_name] = previous_status.pop(old_name)
        # Update persistent JSON
        stores = load_stores()
        stores.pop(old_name, None)
        stores[new_name] = new_ip
        save_stores(stores)
    return jsonify({"success": True})

@app.route('/add', methods=['POST'])
def add_device():
    data = request.json
    name = data['name']
    ip = data['ip']
    if name not in status_data:
        status_data[name] = {"ip": ip, "status": "UNKNOWN", "latency": []}
        previous_status[name] = "UNKNOWN"
        # Update persistent JSON
        stores = load_stores()
        stores[name] = ip
        save_stores(stores)
    return jsonify({"success": True})

# ---------------- App Entry Point ----------------
if __name__ == "__main__":
    Thread(target=update_status, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
