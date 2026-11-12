import pytest
from fastapi.testclient import TestClient

import credit_wallet
from payment_sandbox import build_sandbox_app


@pytest.mark.parametrize("mode,flag",[("live","1"),("sandbox","0"),("live","0")])
def test_test_harness_refuses_live_or_implicit_setup(monkeypatch,mode,flag):
    monkeypatch.setenv("PAYPAL_ENVIRONMENT",mode)
    monkeypatch.setenv("LOCKX_SANDBOX_TEST_SERVICE",flag)
    with pytest.raises(RuntimeError):
        build_sandbox_app()


def test_isolated_test_service_reuses_credit_routes(monkeypatch,tmp_path):
    monkeypatch.setenv("PAYPAL_ENVIRONMENT","sandbox")
    monkeypatch.setenv("LOCKX_SANDBOX_TEST_SERVICE","1")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN","lockx-test.up.railway.app")
    monkeypatch.setenv("LOCKX_DATA_DIR","/data/lockx-sandbox-payments")
    monkeypatch.setattr(credit_wallet,"origin",credit_wallet.origin)
    app=build_sandbox_app()
    monkeypatch.setenv("LOCKX_DATA_DIR",str(tmp_path))
    with TestClient(app) as client:
        assert client.get('/health').json()=={"status":"ok","environment":"sandbox"}
        assert "TEST FUNDS ONLY" in client.get('/').text
        assert client.get('/api/v1/credits/wallet').json()['balance']==0
        assert credit_wallet.origin()=='https://lockx-test.up.railway.app'
