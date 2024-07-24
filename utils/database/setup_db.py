import os
import random
import string
import logging
from datetime import datetime, timedelta, timezone
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import (
    BlobServiceClient,
    generate_container_sas,
    ContainerSasPermissions,
)
from azure.core.exceptions import AzureError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def generate_password(length=16):
    return "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(length)
    )


def parse_connection_string(conn_string):
    return dict(part.split("=", 1) for part in conn_string.split(";") if part)


def create_container_and_sas(conn_string, container_name):
    try:
        blob_service = BlobServiceClient.from_connection_string(conn_string)
        blob_service.create_container(container_name)
        logging.info(f"Container '{container_name}' created.")

        conn_parts = parse_connection_string(conn_string)
        account_name, account_key = (
            conn_parts.get("AccountName"),
            conn_parts.get("AccountKey"),
        )

        if not account_name or not account_key:
            raise ValueError(
                "Invalid connection string: missing AccountName or AccountKey"
            )

        return generate_container_sas(
            account_name,
            container_name,
            account_key=account_key,
            permission=ContainerSasPermissions(
                read=True,
                write=True,
                delete=True,
                list=True,
                add=True,
                create=True,
                delete_previous_version=True,
                permanent_delete=True,
                set_immutability_policy=True,
                tag=True,
            ),
            expiry=datetime.now(timezone.utc) + timedelta(days=730),
        )
    except AzureError as e:
        logging.error(f"Azure operation failed: {str(e)}")
        raise


def create_key_vault_secrets(prefix, key_vault_name, conn_string):
    try:
        secret_client = SecretClient(
            vault_url=f"https://{key_vault_name}.vault.azure.net/",
            credential=DefaultAzureCredential(),
        )

        container_name = prefix.lower()
        blob_sas = create_container_and_sas(conn_string, container_name)
        storage_account_name = parse_connection_string(conn_string).get("AccountName")

        secrets = {
            f"{prefix}-db-username": f"{prefix}_user",
            f"{prefix}-db-password": generate_password(),
            f"{prefix}-storage-account-name": storage_account_name,
            f"{prefix}-blob-sas": blob_sas,
            f"{prefix}-connection-string": conn_string,
        }

        for name, value in secrets.items():
            secret_client.set_secret(name, value)
            logging.info(f"Secret '{name}' set in Key Vault")

        logging.info(f"All secrets created in Azure Key Vault for prefix: {prefix}")
        logging.info(f"Container '{container_name}' created with a 2-year SAS token")
    except AzureError as e:
        logging.error(f"Azure operation failed: {str(e)}")
        raise
    except ValueError as e:
        logging.error(str(e))
        raise


def main():
    try:
        prefix = input("Enter the prefix for the new database: ").strip()
        if not prefix:
            raise ValueError("Prefix cannot be empty")

        key_vault_name = os.getenv("AZURE_KEY_VAULT_NAME", "k8s-homelab-production")
        conn_string = os.getenv("HL_AZ_CONN_STRING")

        if not conn_string:
            raise ValueError("HL_AZ_CONN_STRING environment variable is not set")

        create_key_vault_secrets(prefix, key_vault_name, conn_string)
    except ValueError as e:
        logging.error(str(e))
    except Exception as e:
        logging.error(f"An unexpected error occurred: {str(e)}")


if __name__ == "__main__":
    main()
