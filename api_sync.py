from flask import Blueprint, jsonify, request
import os

sync_bp = Blueprint('sync', __name__)
SYNC_TOKEN = os.environ.get('SYNC_TOKEN', 'zinar-sync-token-2026')

@sync_bp.route('/api/sync/subscribers', methods=['GET'])
def get_subscribers():
    token = request.headers.get('X-Sync-Token') or request.args.get('token')
    if token != SYNC_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    from app import Subscriber
    subs = Subscriber.query.all()
    return jsonify({
        'subscribers': [{
            'username': s.username, 'password': s.password,
            'status': s.status, 'package': s.package,
            'user_type': s.user_type
        } for s in subs],
        'count': len(subs)
    })
