"""Five paired scenarios, ten local HTTP requests, no client retries."""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from run_live import CASES, URL


def main():
    target = Path(__file__).with_name(f'comparison_{datetime.now():%Y%m%d_%H%M%S}.json')
    results = []
    for index in (0, 3, 5, 6, 8):
        case_id, question, products, expectation = CASES[index]
        for model in ('haiku', 'sonnet'):
            payload = dict(question=question, products=products, model=model)
            record = dict(id=case_id, request=payload, expectation=expectation)
            req = urllib.request.Request(URL, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                         headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            start = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=180) as response:
                    record['http_status'] = response.status
                    record['response'] = json.loads(response.read())
            except urllib.error.HTTPError as error:
                record['http_status'] = error.code
                record['error'] = error.read().decode(errors='replace')[:2000]
            except Exception as error:
                record['error'] = str(error)
            record['seconds'] = round(time.perf_counter() - start, 3)
            results.append(record)
            target.write_text(json.dumps({'url': URL, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(record, ensure_ascii=True), flush=True)
    print(f'Results: {target}', flush=True)


if __name__ == '__main__':
    main()
