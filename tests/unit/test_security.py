from ladelaug_avregning.security import (
    hash_password,
    hash_token,
    needs_rehash,
    new_session_token,
    verify_password,
)

# Small params keep the test fast; production params come from config.
FAST = {"time_cost": 1, "memory_cost": 8192, "parallelism": 1}


def test_verify_accepts_correct_rejects_wrong():
    h = hash_password("correct horse", **FAST)
    assert verify_password(h, "correct horse") is True
    assert verify_password(h, "Tr0ub4dor") is False


def test_hash_is_salted():
    assert hash_password("same", **FAST) != hash_password("same", **FAST)


def test_needs_rehash_when_params_increase():
    h = hash_password("pw", **FAST)
    assert needs_rehash(h, time_cost=3, memory_cost=65536, parallelism=2) is True
    assert needs_rehash(h, **FAST) is False


def test_verify_rejects_garbage_hash():
    assert verify_password("not-a-hash", "pw") is False


def test_session_token_shape():
    tok = new_session_token()
    assert 40 <= len(tok) <= 64
    assert tok.replace("-", "").replace("_", "").isalnum()


def test_hash_token_deterministic_hex():
    a = hash_token("abc")
    assert a == hash_token("abc")
    assert len(a) == 64
    int(a, 16)  # valid hex
