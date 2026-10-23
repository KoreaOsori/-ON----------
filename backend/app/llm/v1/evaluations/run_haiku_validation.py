"""Ten local Haiku HTTP requests; no client retries."""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from run_live import URL

CASES = [
    ('01_three_drugs', '코푸시럽, 셉트린정, 코데농정 제품을 함께 먹어도 되나요?', ['코데농정']),
    ('02_three_drugs_repeat', '코푸시럽, 셉트린정, 코데농정 제품을 함께 먹어도 되나요?', ['코데농정']),
    ('03_partial_pair', '코데농정과 코푸시럽을 함께 먹어도 되나요? 성분 중복과 병용금기를 구분해서 알려주세요.', []),
    ('04_unmapped_pair', '이 두 제품을 함께 먹어도 되나요?', ['용각산', '원비디']),
    ('05_overview', '코푸시럽, 셉트린정, 코데농정 해당 약품에 대해 설명해줘요', ['코데농정']),
    ('06_caution', '코푸시럽을 먹을 때 주의할 점과 부작용을 알려주세요.', []),
    ('07_excluded', '코데농정12345는 복용하지 않아요. 용각산의 효능만 알려주세요.', []),
    ('08_excluded_repeat', '코데농정12345는 복용하지 않아요. 용각산의 효능만 알려주세요.', []),
    ('09_unknown', '코푸시럽, 셉트린정, 코데농정12345 제품을 함께 먹어도 되나요?', []),
    ('10_supplement', '코푸시럽과 오메가3를 같이 먹어도 되나요?', []),
]


def main():
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S')
    target = Path(__file__).with_name(f'haiku_validation_{stamp}.json')
    results = []
    for case_id, question, products in CASES:
        payload = dict(question=question, products=products, model='haiku')
        record = dict(id=case_id, request=payload)
        start = time.perf_counter()
        try:
            req = urllib.request.Request(URL, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                         headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
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
        target.write_text(json.dumps(dict(url=URL, timezone='Asia/Seoul', results=results), ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"{case_id}: HTTP {record.get('http_status')} {record.get('response', {}).get('status', 'error')} {record['seconds']}s", flush=True)
    print(f'Results: {target}', flush=True)


if __name__ == '__main__':
    main()
