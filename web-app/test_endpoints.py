#!/usr/bin/env python3
"""Quick test of web-app endpoints (no Spark/Docker required)."""

import sys

def test():
    from app import app
    with app.test_client() as c:
        # Test verify-whitespace
        r = c.post("/config/verify-whitespace", json={"content": "source:\n  type: cassandra\n  host: x"})
        assert r.status_code == 200, r.data
        d = r.get_json()
        assert d.get("success") and "issues" in d
        print("verify-whitespace: OK")

        # Test verify-whitespace with tab
        r2 = c.post("/config/verify-whitespace", json={"content": "source:\n\ttype: cassandra"})
        d2 = r2.get_json()
        assert d2.get("has_issues") and len(d2.get("issues", [])) > 0
        print("verify-whitespace (tab detection): OK")

        # Test test-access with minimal config
        cfg = """source:
  type: cassandra
  host: nonexistent.example
  port: 9042
  keyspace: ks
  table: t
target:
  type: scylla
  host: nonexistent.example
  port: 9042
  keyspace: ks
  table: t
savepoints:
  path: /tmp
  intervalSeconds: 300
"""
        r3 = c.post("/config/test-access", json={"content": cfg})
        assert r3.status_code == 200, r3.data
        d3 = r3.get_json()
        assert "source" in d3 and "target" in d3
        print("test-access: OK")

        print("All web-app endpoint tests passed")
        return 0
    return 1

if __name__ == "__main__":
    sys.exit(test())
