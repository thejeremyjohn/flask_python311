import os

# from cryptography.hazmat.backends import default_backend
# from cryptography.hazmat.primitives import hashes, serialization
# from cryptography.hazmat.primitives.asymmetric import padding

from datetime import timedelta
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from flask import Flask, Request
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy, model
from flask_jwt_extended import JWTManager
from werkzeug.middleware.proxy_fix import ProxyFix


class Dict_(dict):
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            raise KeyError_(f"missing '{key}'")


class KeyError_(KeyError, Exception):
    def __str__(self, *args):
        return Exception.__str__(self, *args)


class Request_(Request):
    def params_(self, nullable=True):
        params = Dict_(self.json or self.form or {})
        if not nullable:
            assert params, f"expected json or form data, got {params}"
        return params
    params = property(params_)

    def add_props_(self, default=''):
        return self.args.get('add_props', default).split(',')
    add_props = property(add_props_)

    def expand_(self, default=''):
        return self.args.get('expand', default).split(',')
    expand = property(expand_)

    @property
    def ip_address(self):
        headers_list = self.headers.get('X-Forwarded-For', '').split(', ')
        return headers_list[0] or self.remote_addr


class Flask_(Flask):
    request_class = Request_


class Config(object):
    DEBUG = False
    TESTING = False
    RELEASE_STAGE = os.environ.get('RELEASE_STAGE', 'local').lower()

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    S3_BUCKET = os.environ.get('S3_BUCKET').lower()
    S3_ASSETS_DIR = f"assets/{RELEASE_STAGE}"

    S3_ASSETS = f"s3://{S3_BUCKET}/{S3_ASSETS_DIR}"

    # CLOUDFRONT_URL = 'https://d14rrnndiq61gj.cloudfront.net'
    # CLOUDFRONT_DISTRIBUTION_ID = 'E2W1E944WWG47Z'
    # CLOUDFRONT_SIGNER = mk_cloudfront_signer(
    #     key_id='APKAIMYBUSD4ZHKVTWLA',
    #     # key_file_path=f"s3://{S3_BUCKET}/cloudfront_key_file/pk-APKAIMYBUSD4ZHKVTWLA.pem",
    # )

    REMEMBER_DURATION = 1  # days
    MAX_REMEMBER_DURATION = 30  # days
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    JWT_TOKEN_LOCATION = ['headers', 'query_string']
    SECRET_KEY = os.urandom(16)

    ITEMS_PER_PAGE = 20
    ITEMS_MAX_PER_PAGE = 100


class DevelopmentConfig(Config):
    DEBUG = True

    SQL_DB_USER = os.environ.get('SQL_DB_USER')
    SQL_DB_PASSWORD = os.environ.get('SQL_DB_PASSWORD')
    SQL_DB_HOST = os.environ.get('SQL_DB_HOST')
    SQL_DB_PORT = os.environ.get('SQL_DB_PORT')
    SQL_DB_NAME = os.environ.get('SQL_DB_NAME')
    SQLALCHEMY_DATABASE_URI = (f"postgresql://{SQL_DB_USER}:{SQL_DB_PASSWORD}"
                               f"@{SQL_DB_HOST}:{SQL_DB_PORT}/{SQL_DB_NAME}")


class TestingConfig(DevelopmentConfig):
    TESTING = True


db = SQLAlchemy()
jwt = JWTManager()
migrate = Migrate()


def create_app(config_class):
    app = Flask_(__name__)
    app.config.from_object(config_class)

    num_proxies = int(os.environ.get('NUM_PROXIES', 0))
    if num_proxies > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=num_proxies)

    return app


def init_app(app):
    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)


def get_ip_address(request):
    headers_list = request.headers.get('X-Forwarded-For', '').split(', ')
    ip_address = headers_list[0] or request.remote_addr
    return ip_address


# def mk_cloudfront_signer(key_id='', key_file_path=''):
#     key_id = key_id or os.environ['CLOUDFRONT_KEY_ID']

#     if key_file_path:
#         with smart_open.smart_open(key_file_path, 'rb') as f:
#             pem_private_key = f.read()
#     else:
#         # pem_private_key = base64.b64decode(os.environ['CLOUDFRONT_KEY_B64'].encode())
#         pem_private_key = os.environ['CLOUDFRONT_KEY'].encode()

#     private_key = serialization.load_pem_private_key(
#         pem_private_key,
#         password=None,
#         backend=default_backend()
#     )

#     def rsa_signer(message):
#         return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())

#     return CloudFrontSigner(key_id, rsa_signer)
app = create_app(DevelopmentConfig)
from . import models
from .core import apiv1
app.register_blueprint(apiv1, url_prefix='/api/v1')


@app.shell_context_processor
def make_shell_context():
    return {
        **{k: v for k, v in models.__dict__.items()
           if isinstance(v, model.DefaultMeta)},
        'db': db,
    }
