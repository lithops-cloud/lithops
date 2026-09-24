---
name: Bug report
about: Something does not work as documented
labels: bug
---

**What happened**
A clear description of the bug and what you expected instead.

**Minimal reproduction**
```python
# the smallest script that reproduces it
import lithops

fexec = lithops.FunctionExecutor()
```

**Traceback / logs**
```
paste the full traceback; if possible, run with log_level: DEBUG
```

**Environment**
- Lithops version (`lithops --version`):
- Compute backend (e.g. `localhost`, `aws_lambda`, `code_engine`, `aws_ec2`):
- Storage backend (e.g. `localhost`, `aws_s3`, `ibm_cos`):
- Runtime (default or custom image):
- Python version and OS of the client:

<!-- Remove credentials and account IDs from any configuration you paste. -->
