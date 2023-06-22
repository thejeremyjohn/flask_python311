from flask import request, jsonify, Blueprint

apiv1 = Blueprint('apiv1', __name__)
apiv2 = Blueprint('apiv2', __name__)

from app import app, db, jwt, get_ip_address


@apiv1.route('/', methods=['GET'])
@apiv1.route('/ping', methods=['GET'])
def ping():
    app.logger.info(f"client IPs: {get_ip_address(request)}")
    return jsonify({'ping': 'pong'})
