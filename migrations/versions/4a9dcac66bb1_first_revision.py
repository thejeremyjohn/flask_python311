"""first_revision

Revision ID: 4a9dcac66bb1
Revises: 
Create Date: 2023-06-22 10:21:38.370264

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a9dcac66bb1'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text('''
        CREATE OR REPLACE FUNCTION update_modified_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.modified = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';

        CREATE TABLE users (
            id int NOT NULL PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );
        ALTER TABLE users
            ADD COLUMN created TIMESTAMPTZ DEFAULT now(),
            ADD COLUMN modified TIMESTAMPTZ DEFAULT now();
        CREATE TRIGGER update_users_modified BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE PROCEDURE update_modified_column();

        CREATE SEQUENCE users_id_seq OWNED BY users.id;
        ALTER TABLE users ALTER COLUMN id SET DEFAULT nextval('users_id_seq');
        UPDATE users SET id = nextval('users_id_seq');
'''))


def downgrade():
    op.get_bind().execute(sa.text('''
        DROP TABLE users CASCADE;
        DROP TRIGGER IF EXISTS update_users_modified ON users;
    '''))
