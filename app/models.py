import os
import sqlparse

from app import app, db, init_app
from flask import jsonify, request
from flask_sqlalchemy import BaseQuery
from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import validates
from uuid import uuid1, uuid4
from validate_email import validate_email
from werkzeug.security import generate_password_hash, check_password_hash

# flask db upgrade will fail if the table is ostensibly
# mapped here but does not yet exist in the actual db.
# export environment variable UPGRADE=1 as a workaround
upgrade = os.environ.get('UPGRADE') == '1'
metadata = MetaData() if upgrade else db.metadata
Base = automap_base(metadata=metadata)


def relationship(*args, **kwargs):
    # because db.relationship is not informed by db.Model|DBModel.query_class
    return db.relationship(*args, **kwargs, query_class=CustomBaseQuery)


class CustomBaseQuery(BaseQuery):
    def get_by_uuid(self, uuid):
        return self.filter_by(uuid=uuid).one_or_none()

    def last(self):
        entity = self.column_descriptions[0].get('entity')
        return self.order_by(entity.id.desc()).first()

    def random(self):
        return self.order_by(db.func.random()).first()

    def get_each(self, attr, *args, callable=False, **kwargs):
        if isinstance(attr, (list, tuple)):
            list_or_tuple = type(attr)
            return [list_or_tuple(getattr(x, a) for a in attr) for x in self]
        elif callable:
            return [getattr(x, attr)(*args, **kwargs) for x in self]
        return [getattr(x, attr) for x in self]

    def set_each(self, attr, value):
        [setattr(x, attr, value) for x in self]

    def map(self, func):
        return map(func, self)

    @property
    def sql(self):
        statement = self.statement.compile(
            compile_kwargs={'literal_binds': True},
            dialect=postgresql.dialect(),
        )
        return sqlparse.format(str(statement), reindent=True)

    def order_by_request_args(self):
        order_by = request.args.get('order_by', 'created')
        reverse = request.args.get('reverse', False, type=util.string_to_bool)
        asc_or_desc = db.desc if reverse else db.asc  # ascending or descending
        first_entity = self.column_descriptions[0]['entity']  # e.g. Asset
        property = getattr(first_entity, order_by)  # e.g. Asset.created

        return self.order_by(asc_or_desc(property))

    def paginate_by_request_args(self):
        items_per_page = request.args.get('per_page', app.config['ITEMS_PER_PAGE'], type=int)
        items_per_page = min(items_per_page, app.config['ITEMS_MAX_PER_PAGE'])
        max_page = self.paginate(1, items_per_page).pages or 1
        page = request.args.get('page', max_page, type=int)
        items = self.paginate(page, items_per_page, error_out=False).items

        return page, items


class DBModel(db.Model):
    __abstract__ = True
    query_class = CustomBaseQuery

    def __init__(self, *args, **kwargs):
        assert not kwargs.get('id'), "'id' cannot be manually set"
        # assert not kwargs.get('uuid'), "'uuid' cannot be manually set" # TODO reapply
        super().__init__(*args, **kwargs)

    def attrs_(self, expand=[], adhoc_expandables={}, add_props=[]):
        attrs = {c.name: getattr(self, c.name) for c in self.__table__.columns}  # json serializable
        expandables = self.get_expandables(adhoc_expandables=adhoc_expandables)

        for expansions in [e.split('.') for e in expand if e]:
            assert len(expansions) <= 4, "expansions have a max depth of 4 levels"
            e = expansions.pop(0)
            assert e in expandables, f"{e} is not a valid expandable for {self.__tablename__}"

            attrs.pop(expandables[e], None)  # remove this foreign key property, e.g. user_id
            thing = self.__getattribute__(e)  # get the thing that was ref'd by that fkey, e.g. user
            attrs[e] = thing.attrs_(expand=['.'.join(expansions)]) if thing else None

        for prop in add_props:
            if prop:
                try:
                    attrs[prop] = self.__getattribute__(prop)
                except AttributeError:
                    if '.' in prop:  # a nested add_prop like "marker.url_blur"
                        prop = prop.split('.')
                        assert len(prop) == 2, "nested add_props have a max depth of 2 levels"
                        a, b = prop
                        if isinstance(attrs[a], dict):
                            attrs[a][b] = self.__getattribute__(a).__getattribute__(b)
                    else:
                        raise
        return attrs
    attrs = property(attrs_)

    # @property
    # def owners(self):
    #     if hasattr(self, 'users'):
    #         owners = self.users
    #         if isinstance(owners, list):
    #             owner_ids = [u.id for u in owners]
    #             return User.query.filter(User.id.in_(owner_ids))
    #     elif hasattr(self, 'user'):
    #         owners = self.user
    #         if isinstance(owners, User):
    #             return User.query.filter(User.id == self.user.id)
    #     else:
    #         owners = User.query.filter(False)  # empty query

    #     return owners

    @validates('id', 'uuid')
    def validate_id_or_uuid(self, key, value):
        if request:  # ensure validation does not apply in flask shell
            old_value = getattr(self, key)
            assert old_value in {None, value}, f"'{key}' cannot be updated"
        return value

    def short_code_(self, short_code_padding=5):
        return util.base36(self.id, zfill=short_code_padding)
    short_code = property(short_code_)

    def get_expandables(self, adhoc_expandables={}):
        expandables = dict()
        for column in self.__table__.get_children():
            if column.foreign_keys:
                try:
                    thing, id = column.description.rsplit('_', 1)  # e.g. "experience", "uuid"
                except ValueError:  # not enough values to unpack (expected 2, got 1)
                    continue  # skip
                if getattr(type(self), thing, None):  # if the model has this InstrumentedAttribute
                    expandables[thing] = column.description
        return {**expandables, **adhoc_expandables}

    @classmethod
    def upsert(self, lookups: dict, _echo=False, **updates) -> tuple:
        '''
        Insert a record which may already exist. If it does, update it.

        Example usage:
            j, = Asset.upsert({'uuid': x}, description=y, name=z)
            _, _ = UserAsset.upsert({'user_id': i 'asset_id': j}, stripe_invoice_id=k)
        '''
        upsert_stmt = (postgresql.insert(self.__table__)
                       .values(**lookups, **updates)
                       .on_conflict_do_update(index_elements=lookups.keys(), set_=updates)
                       .returning(*inspect(self).primary_key))
        if _echo:
            print(upsert_stmt.compile(dialect=postgresql.dialect()))
        return db.session.execute(upsert_stmt).fetchone()


class User(DBModel, Base):
    __tablename__ = 'users'


with app.app_context():
    init_app(app)
    if not upgrade:
        Base.prepare(engine=db.engine, reflect=True)
    db.reflect()
