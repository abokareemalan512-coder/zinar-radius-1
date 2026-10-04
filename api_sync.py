from flask import Blueprint, jsonify, request
from datetime import datetime
import os

sync_bp = Blueprint('sync', __name__)
SYNC_TOKEN = os.environ.get('SYNC_TOKEN', 'zinar-sync-token-2026')

# تخزين آخر سرعة بالذاكرة
_traffic_data = {}

@sync_bp.route('/api/sync/subscribers', methods=['GET'])
def get_subscribers():
    token = request.headers.get('X-Sync-Token') or request.args.get('token')
    if token != SYNC_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    from app import Subscriber, Package
    subs = Subscriber.query.all()
    result = []
    for s in subs:
        pkg = Package.query.filter_by(name=s.package).first() if s.package else None
        result.append({
            'username': s.username, 'password': s.password,
            'status': s.status, 'package': s.package,
            'user_type': s.user_type,
            'expires_at': s.expires_at.isoformat() if s.expires_at else None,
            'duration': pkg.duration if pkg else None,
            'duration_unit': pkg.duration_unit if pkg else None,
        })
    return jsonify({'subscribers': result, 'count': len(result)})

@sync_bp.route('/api/sync/mark-first-use', methods=['POST'])
def mark_first_use():
    token = request.headers.get('X-Sync-Token')
    if token != SYNC_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json() or {}
    updates = data.get('updates', [])
    from app import Subscriber, Package, calculate_expiry, db
    count = 0
    for u in updates:
        sub = Subscriber.query.filter_by(username=u['username']).first()
        if not sub or sub.first_used_at:
            continue
        try:
            sub.first_used_at = datetime.fromisoformat(u['first_used_at'])
        except Exception:
            continue
        pkg = Package.query.filter_by(name=sub.package).first() if sub.package else None
        if pkg and pkg.duration:
            sub.expires_at = calculate_expiry(pkg, sub.first_used_at)
            count += 1
    db.session.commit()
    return jsonify({'ok': True, 'updated': count})

@sync_bp.route('/api/traffic/update', methods=['POST'])
def traffic_update():
    token = request.headers.get('X-Sync-Token')
    if token != SYNC_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json() or {}
    global _traffic_data
    _traffic_data = data
    return jsonify({'ok': True})

@sync_bp.route('/api/traffic/get', methods=['GET'])
def traffic_get():
    return jsonify(_traffic_data)
