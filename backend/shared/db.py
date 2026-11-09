"""Short transactions through RDS Proxy with verified TLS and IAM client auth."""

from contextlib import contextmanager
import os
from pathlib import Path
import ssl


def tls_context():
    # Proxy uses ACM-issued certificates: retain the system trust store. Also load
    # the regional RDS bundle explicitly for AWS RDS certificate trust. A bundle
    # alone is insufficient for the ACM certificate presented by RDS Proxy.
    context = ssl.create_default_context()
    ca_file = Path(os.environ.get("RDS_CA_BUNDLE", Path(__file__).parent / "certs" / "us-west-2-bundle.pem"))
    if not ca_file.is_file():
        raise RuntimeError("The verified AWS RDS CA bundle is missing from the deployment package")
    context.load_verify_locations(cafile=str(ca_file))
    for amazon_root in sorted(ca_file.parent.glob("AmazonRootCA*.pem")):
        context.load_verify_locations(cafile=str(amazon_root))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def connect():
    import boto3
    import pg8000.dbapi

    if os.environ.get("DB_AUTH", "iam") != "iam":
        raise RuntimeError("Only IAM authentication to RDS Proxy is supported")
    host = os.environ["DB_HOST"]
    user = os.environ.get("DB_USER", "retail_app")
    token = boto3.client("rds").generate_db_auth_token(DBHostname=host, Port=5432, DBUsername=user)
    return pg8000.dbapi.connect(
        host=host,
        port=5432,
        database=os.environ.get("DB_NAME", "retail"),
        user=user,
        password=token,
        ssl_context=tls_context(),
        timeout=5,
        tcp_keepalive=True,
        application_name="cloudathon-retail",
    )


@contextmanager
def transaction():
    connection = connect()
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def rows(cursor):
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def one(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip((column[0] for column in cursor.description), row))


def ensure_customer(cursor, subject):
    cursor.execute("INSERT INTO customers (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (subject,))
