import { useMutation } from "@tanstack/react-query";
import { useBlocker } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { postPreview, postSave, Refused } from "@/shared/api/library";
import type { Draft, JobState, LibraryJob } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { emptyDraft, isEmpty, type PageDraft } from "./draft";
import { useJobFollow } from "./useJobFollow";

// The sentence of the server's refusal that Reload answers.
const STALE = "the album changed since this page loaded";

interface Options {
	/** A save the page was served with, followed from the job route. */
	adopted: { id: string; state: JobState } | null | undefined;
	/** Where this page's part of the job stands; `undefined` until the job names it. */
	stateOf: (job: LibraryJob) => JobState | undefined;
	/** The sentence a failed job gives for this page. */
	errorOf: (job: LibraryJob) => string | null | undefined;
	/** Runs once when the job is done, after the draft is cleared. */
	onDone: (job: LibraryJob | undefined) => Promise<void>;
	/** Runs once when the job has failed; the draft stays. */
	onFailed?: (job: LibraryJob | undefined) => void;
	/** Runs when the server accepts a save or no longer knows its job, so the page's own queries are asked again. */
	refresh?: () => void;
}

const servedSentence = (error: unknown) =>
	error instanceof Refused ? error.sentence : null;

/** A page's draft, its preview, and the save that follows it to a done or failed job. */
export function useDraftFlow(options: Options) {
	const { t } = useTranslate();
	const latest = useRef(options);
	useEffect(() => {
		latest.current = options;
	});

	const [draft, setDraft] = useState<PageDraft>(emptyDraft);
	// The draft as it is now. The leave check must see one cleared in the same tick as the move, and a change made after an async step builds on it.
	const draftNow = useRef(draft);
	const [preview, setPreview] = useState<Awaited<
		ReturnType<typeof postPreview>
	> | null>(null);
	// Bumped by every change of the draft: an answer made from an older one is not the page's.
	const draftVersion = useRef(0);
	const [previewFailed, setPreviewFailed] = useState(false);
	const [message, setMessage] = useState<string | null>(null);
	// The job a failure ended, kept so its reasons stay on the page until the next edit.
	const [outcome, setOutcome] = useState<LibraryJob | null>(null);

	const changeDraft = useCallback(
		(change: PageDraft | ((now: PageDraft) => PageDraft)) => {
			const next =
				typeof change === "function" ? change(draftNow.current) : change;
			draftNow.current = next;
			draftVersion.current += 1;
			setDraft(next);
			setPreview(null);
			setPreviewFailed(false);
			setOutcome(null);
		},
		[],
	);

	const discard = useCallback(() => {
		changeDraft(emptyDraft);
		setMessage(null);
	}, [changeDraft]);

	const blocker = useBlocker({
		shouldBlockFn: () => !isEmpty(draftNow.current),
		enableBeforeUnload: () => !isEmpty(draftNow.current),
		withResolver: true,
	});

	const { job, state, follow } = useJobFollow({
		adopted: options.adopted,
		stateOf: options.stateOf,
		onDone: (finishedJob) => {
			discard();
			return latest.current.onDone(finishedJob);
		},
		onFailed: (failedJob) => {
			setMessage(
				(failedJob && latest.current.errorOf(failedJob)) ?? t("library.failed"),
			);
			setOutcome(failedJob ?? null);
			latest.current.onFailed?.(failedJob);
		},
		onGone: () => {
			setMessage(t("library.interrupted"));
			latest.current.refresh?.();
		},
	});

	const previewing = useMutation({ mutationFn: postPreview });
	const saving = useMutation({
		mutationFn: postSave,
		onSuccess: (answer) => {
			follow(answer.job);
			latest.current.refresh?.();
		},
		onError: (error) =>
			setMessage(servedSentence(error) ?? t("library.failed")),
	});

	return {
		draft,
		changeDraft,
		discard,
		preview,
		/** The job being followed, once it has answered. */
		job,
		/** The job a failure ended, until the draft changes. */
		outcome,
		message,
		stale: message === STALE,
		/** A save is running, or being asked for: nothing may change under it. */
		readOnly: state !== null || saving.isPending,
		state,
		blocker,
		/** The preview failed with no sentence of the server's to show. */
		previewFailed,
		previewPending: previewing.isPending,
		review(wire: Draft) {
			setMessage(null);
			setPreviewFailed(false);
			const asked = draftVersion.current;
			previewing.mutate(wire, {
				onSuccess: (answer) => {
					if (draftVersion.current === asked) setPreview(answer);
				},
				onError: (error) => {
					if (draftVersion.current !== asked) return;
					const sentence = servedSentence(error);
					if (sentence === null) setPreviewFailed(true);
					else setMessage(sentence);
				},
			});
		},
		save(wire: Draft) {
			setMessage(null);
			setPreview(null);
			saving.mutate(wire);
		},
	};
}
