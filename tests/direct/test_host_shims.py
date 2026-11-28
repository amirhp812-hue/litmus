"""The host-call helpers of conftest.py, tested with a stand-in calldata codec (no GenVM needed)."""
import json
import pickle

from conftest import reply_as_text, transfer_from_request


class Codec:
    """Stand-in for genlayer's calldata module: any reversible codec will do for these tests."""
    encode = staticmethod(pickle.dumps)
    decode = staticmethod(pickle.loads)


class Address:
    def __init__(self, raw):
        self.raw = raw

    def __bytes__(self):
        return self.raw


WALLET = bytes.fromhex("AB" * 20)


def test_post_message_transfer_is_recorded_with_its_delivery_flag():
    request = {"PostMessage": {"address": Address(WALLET), "calldata": {}, "value": 6000, "on": "finalized"}}
    assert transfer_from_request(request) == {"to": "0x" + "ab" * 20, "value": 6000, "method": None, "on": "finalized"}


def test_eth_send_to_a_wallet_is_recorded_without_a_delivery_flag():
    request = {"EthSend": {"address": Address(WALLET), "calldata": b"", "value": 9000}}
    assert transfer_from_request(request) == {"to": "0x" + "ab" * 20, "value": 9000, "method": None, "on": None}


def test_v06_abi_method_key_and_hex_addresses_are_understood():
    class Hexed:
        as_hex = "0x" + "CD" * 20
    request = {"PostMessage": {"address": Hexed(), "calldata": {"": "ping"}, "value": 1, "on": "accepted"}}
    assert transfer_from_request(request) == {"to": "0x" + "cd" * 20, "value": 1, "method": "ping", "on": "accepted"}


def test_other_host_requests_are_not_transfers():
    assert transfer_from_request({"ExecPrompt": {"prompt": "x"}}) is None
    assert transfer_from_request({"CallContract": {"address": Address(WALLET)}}) is None
    assert transfer_from_request({"PostMessage": {"address": Address(WALLET)}}) is None   # no value: not a transfer
    assert transfer_from_request("not a request") is None


def test_json_answers_of_a_model_call_become_text_again():
    request = {"ExecPrompt": {"prompt": "LITMUS ..."}}
    ruling = {"verdict": "BREACH", "factors": [True, False], "reason": "Because."}
    reply = reply_as_text(Codec, request, Codec.encode({"ok": ruling}))
    answer = Codec.decode(reply)
    assert set(answer) == {"ok"} and isinstance(answer["ok"], str)
    assert json.loads(answer["ok"]) == ruling


def test_text_answers_errors_and_other_requests_pass_through_untouched():
    text = Codec.encode({"ok": '{"already": "text"}'})
    assert reply_as_text(Codec, {"ExecPrompt": {}}, text) == text
    error = Codec.encode({"error": {"kind": "boom"}})
    assert reply_as_text(Codec, {"ExecPrompt": {}}, error) == error
    other = Codec.encode({"ok": {"a": 1}})
    assert reply_as_text(Codec, {"WebRequest": {}}, other) == other
    assert reply_as_text(Codec, {"ExecPrompt": {}}, b"\xff not decodable") == b"\xff not decodable"
