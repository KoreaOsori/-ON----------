"""Request-local accounting; missing provider usage is never reported as zero."""
FIELDS = ('inputTokens', 'outputTokens', 'totalTokens', 'cacheReadInputTokens', 'cacheWriteInputTokens')


class Usage:
    def __init__(self):
        self.calls = []

    def add(self, stage, usage):
        values = dict(usage or {})
        if 'totalTokens' not in values and all(k in values for k in ('inputTokens', 'outputTokens')):
            values['totalTokens'] = values['inputTokens'] + values['outputTokens']
        self.calls.append((stage, values))

    def snapshot(self):
        def aggregate(calls):
            result = {'calls': len(calls)}
            for field in FIELDS:
                values = [data.get(field, 0 if field.startswith('cache') else None) for _, data in calls]
                result[field] = sum(values) if all(type(v) is int and v >= 0 for v in values) else None
            result['complete'] = all(result[k] is not None for k in ('inputTokens', 'outputTokens', 'totalTokens'))
            return result
        return {**aggregate(self.calls), **{stage: aggregate([c for c in self.calls if c[0] == stage])
                                           for stage in ('routing', 'answer', 'embedding')}}
