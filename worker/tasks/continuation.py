"""Continue text or resume a validated training-plan checkpoint on explicit clicks."""
import copy
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

from worker.celery_app import app
from worker.tasks.ai import _privacy, _run_task, _training_plan, _tracked_chat
from pengucoach.db.models import AiRun, BackgroundJob, Conversation, LlmModel, Message, User
from pengucoach.db.session import SessionLocal
from pengucoach.llm.continuation import append_text, merge_metadata, public
from pengucoach.llm.service import AiGenerationCancelled


async def unlock(user_id, run_id, task_id, status):
    async with SessionLocal() as db:
        run = await db.get(AiRun, uuid.UUID(run_id))
        if run and str(run.user_id) == user_id:
            meta = dict(run.metadata_json or {})
            if (meta.get('_continuation_job') or {}).get('task_id') == task_id:
                meta.pop('_continuation_job', None)
                run.metadata_json = meta
        job = await db.get(BackgroundJob, uuid.UUID(task_id)) if task_id else None
        if job and str(job.user_id) == user_id:
            job.status, job.finished_at = status, datetime.now(timezone.utc)
        await db.commit()


async def _continue(user_id, payload, progress_callback=None, cancel_check=None, task_id=None):
    status = 'failed'
    try:
        async with SessionLocal() as db:
            user = await db.get(User, uuid.UUID(user_id))
            run = await db.get(AiRun, uuid.UUID(payload['run_id']))
            if not user or not run or run.user_id != user.id:
                raise RuntimeError('AI_RUN_NOT_FOUND')
            meta = copy.deepcopy(run.metadata_json or {})
            if (meta.get('continuation') or {}).get('revision') != payload['revision']:
                raise RuntimeError('AI_RUN_CHANGED_RELOAD')
            if task_id and (meta.get('_continuation_job') or {}).get('task_id') != task_id:
                raise RuntimeError('AI_RUN_CHANGED_RELOAD')
            model = await db.get(LlmModel, run.model_id)
            if not model:
                raise RuntimeError('NO_ELIGIBLE_LLM_MODEL_CONFIGURED')
            snapshot = meta.get('_resume') or {}
            previous = run.content
            format_retry = (meta.get('continuation') or {}).get('reason') in {'invalid_plan', 'interrupted'}
            ceiling = min(65536, (model.metadata_json or {}).get('provider_max_output_tokens') or 65536)
            output = min(ceiling, (run.max_output_tokens or 8000) if format_retry else
                (run.max_output_tokens or 0)+8000 if not previous or run.task_type == 'training_plan' else 8000)
            ctx = snapshot.get('context_window_tokens') or meta.get('context_window_tokens') or 8192
            source_context = snapshot.get('context') or (meta.get('_plan_state') or {}).get('context') or {}
            messages = copy.deepcopy(snapshot.get('messages') or [])
            if previous and run.task_type != 'training_plan':
                messages += [{'role': 'assistant', 'content': previous}, {'role': 'user',
                    'content': 'Continue the previous answer exactly where it stopped. Do not repeat earlier text. Finish the remaining points concisely.'}]
            # Size the request from context actually sent, not unbounded raw
            # history. Oversizing num_ctx can allocate needless Ollama KV memory.
            context_chars = min(len(json.dumps(source_context, default=str)), snapshot.get('context_chars') or meta.get('context_chars') or 24000)
            instruction_chars = snapshot.get('instruction_chars') or len((meta.get('_request') or {}).get('prompt') or '')+3500
            needed = (context_chars + sum(len(m.get('content', '')) for m in messages[-12:]) + instruction_chars)//3 + output+1800
            ctx = min(model.context_window or 1048576, max(ctx, needed))
            local_only = await _privacy(db, user)
            if run.task_type == 'training_plan':
                request = dict(meta.get('_request') or {})
                request.update(max_tokens=output, context_window_tokens=ctx, model_id=str(run.model_id),
                    _continue_run_id=str(run.id), _minimum_retry_output=None if format_retry else (run.max_output_tokens or 0)+1,
                    _resume_plan=meta.get('_plan_state') or {'context': source_context})
                # Use the same validated plan generator and preserve prior successful segments.
                result = await _training_plan(user_id, request, progress_callback=progress_callback, cancel_check=cancel_check)
                status = 'finished'
                return result
            if not snapshot:
                raise RuntimeError('AI_RUN_NOT_CONTINUABLE')
            db.info['ai_user_id'] = user.id
            answer = await _tracked_chat(db, messages, source_context, snapshot.get('locale', user.locale), task=run.task_type,
                local_only=local_only, model_id=run.model_id, instruction_prompt=snapshot.get('instruction_prompt'),
                requested_max_tokens=output, requested_context_window_tokens=ctx, quality_profile=snapshot.get('quality_profile', 'standard'),
                progress_callback=progress_callback, cancel_check=cancel_check, recover_limit=True, continuation_mode=True, minimum_output_tokens=(run.max_output_tokens or 0)+1 if not previous else None)
            if cancel_check and cancel_check():
                raise AiGenerationCancelled('AI_JOB_CANCELLED')
            if not previous and answer.get('empty_due_to_limit') and answer['max_output_tokens'] <= (run.max_output_tokens or 0):
                raise RuntimeError('CONTINUATION_MODEL_LIMIT')
            # Serialize final merge after generation; other edits keep their text.
            await db.rollback()
            user = await db.get(User, uuid.UUID(user_id))
            run = await db.scalar(select(AiRun).where(AiRun.id == uuid.UUID(payload['run_id']), AiRun.user_id == user.id)
                .with_for_update().execution_options(populate_existing=True))
            if not run or (run.metadata_json.get('continuation') or {}).get('revision') != payload['revision'] or run.content != previous:
                raise RuntimeError('AI_RUN_CHANGED_RELOAD')
            target = None
            if meta.get('assistant_message_id'):
                target = await db.get(Message, uuid.UUID(meta['assistant_message_id']))
                latest = await db.scalar(select(Message).where(Message.conversation_id == uuid.UUID(meta['conversation_id']))
                    .order_by(Message.created_at.desc(), Message.id.desc()).limit(1))
                if not target or not latest or latest.id != target.id:
                    # Keep a billable attempt in usage history; do not overwrite a changed conversation.
                    db.add(AiRun(user_id=user.id, task_type=run.task_type, model_id=run.model_id,
                        provider_name=answer['provider'], model_name=answer['model'], prompt='Stale continuation',
                        content=answer['content'], metadata_json={**public(answer), 'stale_continuation': True, 'conversation_id': meta.get('conversation_id')}))
                    await db.commit()
                    raise RuntimeError('CONVERSATION_CHANGED_RELOAD')
            merged = append_text(previous, answer['content'])
            updated = merge_metadata(meta, answer)
            updated['continuation'] = {**answer.get('continuation', {}), 'revision': payload['revision']}
            # Keep the original snapshot for repeated continuation, avoiding duplicate assistant prefixes.
            if answer.get('truncated'):
                updated['_resume'] = snapshot | {'context_window_tokens': ctx, 'max_output_tokens': answer['max_output_tokens']}
            run.content, run.metadata_json, run.max_output_tokens = merged, updated, answer['max_output_tokens']
            if target:
                target.content = merged
                target.metadata_json = {**(target.metadata_json or {}), **public(updated), 'run_id': str(run.id)}
                conversation = await db.get(Conversation, target.conversation_id)
                conversation.updated_at = datetime.now(timezone.utc)
            await db.commit()
            status = 'finished'
            return {'run_id': str(run.id), **public(answer), 'content': merged, 'metadata': public(updated),
                'continuation': updated['continuation'], 'usage': updated.get('usage'), 'cost_eur': updated.get('cost_eur'),
                'conversation_id': meta.get('conversation_id')}
    except AiGenerationCancelled:
        status = 'cancelled'
        raise
    finally:
        if task_id:
            await unlock(user_id, payload['run_id'], task_id, status)


@app.task(bind=True, name='worker.tasks.continuation.continue_ai')
def continue_ai(self, user_id, payload):
    return _run_task(self, {**payload, '_no_auto_retry': True}, 'coach', lambda progress, check: _continue(user_id, payload, progress, check, str(self.request.id)))
