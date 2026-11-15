"""Register the actually loaded bundle at startup, independently of model calls."""
import logging

from app.domain.errors import AppError

logger = logging.getLogger('app.llm.capture')


def register_loaded_templates(repository, sources):
    """Preserve immutable snapshots; report failures without fabricating call history."""
    states = {}
    for node, source in sources.items():
        try:
            if repository is None:
                raise AppError('LLM_SNAPSHOT_UNAVAILABLE', '模板快照存储不可用。', 503)
            if source.build().content_hash != source.snapshot.content_hash:
                raise AppError('PROMPT_SOURCE_MISMATCH', '启动时模板来源一致性检查失败。', 503)
            repository.register(source.snapshot)
            states[node] = 'registered'
        except Exception as exc:
            code = exc.error.code if isinstance(exc, AppError) else 'LLM_SNAPSHOT_UNAVAILABLE'
            states[node] = code
            # No request, prompt text, exception body or configuration is logged.
            logger.error('Loaded Prompt registration failed; model call registration checks remain enforced',
                         extra={'node_id': node, 'error_code': code})
    return states
