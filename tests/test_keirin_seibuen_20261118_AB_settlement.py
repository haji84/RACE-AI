"""Source-free synthetic RSA/AES end-to-end tests; no owner key in GitHub CI."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import base64
import json
import unittest
import zlib

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from race_ai import keirin_seibuen_20261118_AB_settlement as bridge
from race_ai import keirin_available_prediction_audit as audit

ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/"docs/evidence/2026-11-18/keirin_seibuen1r_AB_sealed_cipher_v1.json"
COHORT=ROOT/"docs/evidence/2026-11-18/keirin_seibuen1r_active_generated_AB_prereg_v1.json"
RID="202611182601"
AT="2026-11-18T06:53:33+09:00"
CUT="2026-11-18T10:45:00+09:00"


def build_fixture():
    owner=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    keypem=owner.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    pub=owner.public_key()
    pubsha=sha256(pub.public_bytes(serialization.Encoding.DER,
                                  serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    inp="a"*64
    envelopes={}
    for name,picks in (("A",[[3,5,1],[3,5,4]]),
                       ("B",[[5,3,1],[3,5,1]])):
        forecast={"race_id":RID,"generated_at":AT,"ranked_tickets":picks}
        raw_prediction=audit.canonical(forecast)+b"\n"
        kind="EXISTING_GENERATED" if name=="A" else "SIX_PHASE"
        phase={p:"invented hypothesis" for p in audit.PHASES} if name=="B" else None
        arm=audit.make_arm(race_id=RID,arm=kind,
            source_document_sha256=sha256(raw_prediction).hexdigest(),
            common_input_sha256=inp,observed_as_of=AT,
            generated_at=AT,official_cutoff_at=CUT,ranked_tickets=picks,
            phase_hypotheses=phase)
        record={"race_id":RID,"role":name,"source_input_sha256":inp,
            "original_forecast":forecast,"audit_arm":arm,
            "result_observation":None,"not_officially_cutoff_attested":True}
        payload=audit.canonical(record)+b"\n"
        compressed=zlib.compress(payload,9)
        aes_key=AESGCM.generate_key(bit_length=256)
        iv=(b"\x02" if name=="A" else b"\x03")*12
        aad=f"RACE_AI_SEIBUEN_AB_20261118_V1|{RID}|{name}|ZLIB".encode()
        ct=AESGCM(aes_key).encrypt(iv,compressed,aad)
        wrapped=pub.encrypt(aes_key,padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),label=None))
        envelopes[name]={
            "aad_ascii":aad.decode(),
            "aesgcm_nonce_b64":base64.b64encode(iv).decode(),
            "ciphertext_b64":base64.b64encode(ct).decode(),
            "ciphertext_sha256":sha256(ct).hexdigest(),
            "compressed_sha256":sha256(compressed).hexdigest(),
            "plaintext_payload_sha256":sha256(payload).hexdigest(),
            "rsa_oaep_sha256_wrapped_key_b64":base64.b64encode(wrapped).decode()}
    entry={
        "schema":"RACE_AI_KEIRIN_OWNER_AB_DUAL_SEALED_ONE_RACE_V1",
        "race_id":RID,"cohort_sha256":bridge.COHORT_SHA,
        "rsa_public_key_spki_sha256":pubsha,
        "source_pre_race_facts_sha256":inp,
        "published_sales_cutoff_at_jst":CUT,
        "A":envelopes["A"],"B":envelopes["B"]}
    cipher=audit.canonical(entry)+b"\n"
    result={
        "race_id":RID,"status":"FINAL_NORMAL","refund_status":"NONE",
        "source_published_at":"2026-11-18T11:05:00+09:00",
        "observed_at":"2026-11-18T11:06:00+09:00",
        "winning_triples":[[5,3,1]],
        "payouts_100yen":[{"triple":[5,3,1],"yen":1250}]}
    cohort=json.loads(COHORT.read_text(encoding="utf-8"))
    return keypem,cipher,cohort,result


def invoke(key,cipher,cohort,result,**k):
    args={
      "raw_cipher":cipher,"owner_RSA_private_pem":key,
      "cohort":cohort,"official_result":result,
      "verify_git_commit_receipt":lambda a,b,c:True,
      "verify_official_cutoff":lambda a,b:True,
      "verify_official_result":lambda a:True}
    args.update(k)
    with patch.object(bridge,"SHA_FILE",sha256(cipher).hexdigest()):
        return bridge.score_real(**args)


class RealSeibuenABSettlement(unittest.TestCase):
    def test_public_immutable_real_evidence_present_not_decrypted_by_CI(self):
        self.assertEqual(sha256(PUBLIC.read_bytes()).hexdigest(),bridge.SHA_FILE)
        audit.checked_cohort(json.loads(COHORT.read_text()))

    def test_authenticated_decryption_and_fictional_result_scoring(self):
        pem,raw,cohort,result=build_fixture()
        out=invoke(pem,raw,cohort,result)
        self.assertTrue(out["official_outcome_scored"])
        self.assertFalse(out["A_existing"]["hit_at_all"])
        self.assertTrue(out["B_six_phase"]["hit_at_1"])
        self.assertEqual(out["B_six_phase"]["virtual_roi"],1250/200)
        self.assertFalse(out["formal_accuracy_improvement_proven"])

    def test_missing_official_witness_is_HOLD(self):
        pem,raw,cohort,result=build_fixture()
        out=invoke(pem,raw,cohort,result,verify_official_result=None)
        self.assertEqual(out["state"],"HOLD_ORGANIZER_FINAL_RESULT_UNVERIFIED")
        out=invoke(pem,raw,cohort,result,verify_official_cutoff=None)
        self.assertEqual(out["state"],"HOLD_OFFICIAL_CUTOFF_UNATTESTED")

    def test_wrong_RSA_private_key_denied(self):
        pem,raw,cohort,result=build_fixture()
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        forged=other.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        with patch.object(bridge,"SHA_FILE",sha256(raw).hexdigest()):
            with self.assertRaisesRegex(bridge.SealedSettlementError,
                                        "RSA_KEY_FINGERPRINT_MISMATCH"):
                bridge.decode_owner_sealed(
                    raw_cipher=raw,owner_RSA_private_pem=forged)

    def test_modified_encrypted_bytes_rejected(self):
        pem,raw,cohort,result=build_fixture()
        mod=deepcopy(json.loads(raw))
        mod["B"]["ciphertext_sha256"]="f"*64
        bad=audit.canonical(mod)+b"\n"
        with patch.object(bridge,"SHA_FILE",sha256(bad).hexdigest()):
            with self.assertRaisesRegex(bridge.SealedSettlementError,
                                        "AUTHENTICATED_DECRYPTION_FAILED"):
                bridge.decode_owner_sealed(raw_cipher=bad,
                                           owner_RSA_private_pem=pem)

    def test_result_before_cutoff_not_scored(self):
        pem,raw,cohort,result=build_fixture()
        result["source_published_at"]="2026-11-18T10:44:59+09:00"
        with self.assertRaisesRegex(bridge.SealedSettlementError,
                                    "RESULT_TIME_WRONG"):
            invoke(pem,raw,cohort,result)

    def test_unobserved_or_refunded_race_HOLD_not_miss(self):
        pem,raw,cohort,result=build_fixture()
        result["refund_status"]="FULL"
        out=invoke(pem,raw,cohort,result)
        self.assertEqual(out["state"],"HOLD_RESULT_NOT_FINAL_NORMAL")


if __name__=="__main__":
    unittest.main()
