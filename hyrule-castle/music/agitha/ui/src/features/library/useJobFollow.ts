import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
	isGone,
	isSaving,
	libraryJobQuery,
} from "@/domain/library/libraryQuery";
import type { JobState, LibraryJob } from "@/shared/api/types";

interface Options {
	/** A save the page was served with, followed from the job route. */
	adopted: { id: string; state: JobState } | null | undefined;
	/** Where this page's part of the job stands; `undefined` until the job names it. */
	stateOf: (job: LibraryJob) => JobState | undefined;
	/** Runs once when the job is done. */
	onDone: (job: LibraryJob | undefined) => Promise<void>;
	/** Runs once when the job has failed. */
	onFailed: (job: LibraryJob | undefined) => void;
	/** Runs once when the server no longer knows the job. */
	onGone: () => void;
}

/** Follows one save job, the adopted one or the one `follow` names, to its end, and says each end once. */
export function useJobFollow(options: Options) {
	const latest = useRef(options);
	useEffect(() => {
		latest.current = options;
	});

	const [jobId, setJobId] = useState<string | null>(null);
	const finished = useRef(new Set<string>());

	const { adopted } = options;
	const adoptedId =
		adopted && isSaving(adopted.state) && !finished.current.has(adopted.id)
			? adopted.id
			: null;
	const watching = jobId ?? adoptedId;
	const jobQuery = useQuery(libraryJobQuery(watching));
	const job = jobQuery.data;
	const state: JobState | null =
		watching === null
			? null
			: ((job && options.stateOf(job)) ?? adopted?.state ?? "waiting");

	const doneId = state === "done" ? watching : null;
	const failedId = state === "failed" ? watching : null;
	// Jobs live in the server's memory: after a restart the route knows none, and the save did not finish.
	const goneId = isGone(jobQuery.error) ? watching : null;

	useEffect(() => {
		if (doneId === null || finished.current.has(doneId)) return;
		finished.current.add(doneId);
		void latest.current.onDone(job).then(() => setJobId(null));
	}, [doneId, job]);

	useEffect(() => {
		if (failedId === null || finished.current.has(failedId)) return;
		finished.current.add(failedId);
		latest.current.onFailed(job);
		setJobId(null);
	}, [failedId, job]);

	useEffect(() => {
		if (goneId === null || finished.current.has(goneId)) return;
		finished.current.add(goneId);
		setJobId(null);
		latest.current.onGone();
	}, [goneId]);

	return { job, state, follow: setJobId };
}
