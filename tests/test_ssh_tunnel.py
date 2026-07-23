import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.config.settings import Settings
from app.config.ssh_tunnel import (
    SshTunnelManager,
    TunnelEndpoint,
    rewrite_mysql_url,
    rewrite_redis_url,
)


class SshSettingsTests(unittest.TestCase):
    def test_enabled_tunnel_requires_connection_credentials(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                mysql_url="mysql+aiomysql://user:pass@127.0.0.1/db",
                redis_url="redis://127.0.0.1/0",
                ssh_tunnel_enabled=True,
            )

    def test_secret_values_are_hidden_from_settings_repr(self) -> None:
        settings = Settings(
            _env_file=None,
            mysql_url="mysql+aiomysql://user:mysql-secret@127.0.0.1/db",
            redis_url="redis://default:redis-secret@127.0.0.1/0",
            ssh_tunnel_enabled=True,
            ssh_host="server.example.com",
            ssh_username="ubuntu",
            ssh_password="ssh-secret",
        )
        rendered = repr(settings)
        self.assertNotIn("mysql-secret", rendered)
        self.assertNotIn("redis-secret", rendered)
        self.assertNotIn("ssh-secret", rendered)

    def test_explicit_test_settings_ignore_infrastructure_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WEALTHSENSE_APP_ENV": "production",
                "WEALTHSENSE_MYSQL_URL": (
                    "mysql+aiomysql://user:pass@server.example.com/db"
                ),
                "WEALTHSENSE_REDIS_URL": "redis://server.example.com/0",
                "WEALTHSENSE_SSH_TUNNEL_ENABLED": "true",
            },
        ):
            settings = Settings(
                _env_file=None,
                app_env="development",
                mysql_url=None,
                redis_url=None,
                ssh_tunnel_enabled=False,
            )
        self.assertFalse(settings.has_external_infrastructure)
        self.assertFalse(settings.ssh_tunnel_enabled)
        self.assertEqual(settings.app_env, "development")


class SshUrlTests(unittest.TestCase):
    def test_mysql_url_rewrite_preserves_database_and_query(self) -> None:
        rewritten = rewrite_mysql_url(
            "mysql+aiomysql://finance:secret@127.0.0.1:3306/finance"
            "?charset=utf8mb4",
            TunnelEndpoint("127.0.0.1", 45123),
        )
        self.assertEqual(
            rewritten,
            "mysql+aiomysql://finance:secret@127.0.0.1:45123/finance"
            "?charset=utf8mb4",
        )

    def test_redis_url_rewrite_preserves_credentials_and_database(self) -> None:
        rewritten = rewrite_redis_url(
            "redis://default:p%40ss@127.0.0.1:6379/2?socket_timeout=5",
            TunnelEndpoint("127.0.0.1", 46379),
        )
        self.assertEqual(
            rewritten,
            "redis://default:p%40ss@127.0.0.1:46379/2?socket_timeout=5",
        )


class SshTunnelLifecycleTests(unittest.TestCase):
    def test_start_uses_verified_host_keys_and_close_is_idempotent(self) -> None:
        transport = Mock()
        transport.is_active.return_value = True
        client = Mock()
        client.get_transport.return_value = transport

        with tempfile.NamedTemporaryFile() as known_hosts:
            manager = SshTunnelManager(
                ssh_host="server.example.com",
                ssh_port=22,
                ssh_username="ubuntu",
                ssh_password="secret",
                known_hosts=known_hosts.name,
                mysql_remote_host="127.0.0.1",
                mysql_remote_port=3306,
                redis_remote_host="127.0.0.1",
                redis_remote_port=6379,
            )
            with patch(
                "app.config.ssh_tunnel.paramiko.SSHClient",
                return_value=client,
            ):
                manager.start()
                self.assertGreater(manager.mysql_endpoint.port, 0)
                self.assertGreater(manager.redis_endpoint.port, 0)
                manager.close()
                manager.close()

        client.load_host_keys.assert_called_once()
        client.set_missing_host_key_policy.assert_called_once()
        transport.set_keepalive.assert_called_once_with(30)
        client.close.assert_called()


if __name__ == "__main__":
    unittest.main()
