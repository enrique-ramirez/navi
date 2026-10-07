import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { albumKey, isRunning } from "@/domain/album/albumQuery";
import { awaitsKeepChoice } from "@/domain/album/keepChoice";
import { albumUrl, post } from "@/shared/api/album";
import type { AlbumView, CopySide } from "@/shared/api/types";
import type { Pending } from "./pending";

export type Then = { kind: "preview" } | { kind: "approve"; keep?: CopySide };

interface Awaiting {
	then: Then;
	/** Whether the view has shown identify running; the view arrives a render after this state. */
	seen: boolean;
	digest: string | null;
}

export function useDecision(view: AlbumView, pending: Pending) {
	const client = useQueryClient();
	const [refusal, setRefusal] = useState<string | null>(null);
	const [changed, setChanged] = useState(false);
	const [sending, setSending] = useState(false);
	const [awaiting, setAwaiting] = useState<Awaiting | null>(null);

	const running = isRunning(view.state);
	const refresh = () => client.invalidateQueries({ queryKey: albumKey(view) });
	// Move lands the album in the library: its listings are kept for a while and must be asked again.
	const libraryChanged = () =>
		client.invalidateQueries({ queryKey: ["library"] });

	async function submit(path: string, body: unknown) {
		setRefusal(null);
		setChanged(false);
		setSending(true);
		const answer = await post(`${albumUrl(view)}/${path}`, body);
		setSending(false);
		if (!answer.ok) setRefusal(answer.error);
		return answer.ok;
	}

	async function send(then: Then) {
		const digest = view.preview?.plan_digest ?? null;
		if (!(await submit("decision", pending.draft))) return;
		setAwaiting({ then, seen: false, digest });
		await refresh();
	}

	async function approve(keep?: CopySide) {
		const ok = await submit("approve", keep ? { keep } : {});
		if (ok) await refresh();
		return ok;
	}

	async function move() {
		if (await submit("move", {})) {
			void libraryChanged();
			await refresh();
		}
	}

	// biome-ignore lint/correctness/useExhaustiveDependencies: runs when identify finishes, not when the view's other fields change
	useEffect(() => {
		if (awaiting === null) return;
		if (running) {
			if (!awaiting.seen) setAwaiting({ ...awaiting, seen: true });
			return;
		}
		// Identify can finish before a poll sees it run: the view then already holds the sent
		// decision and a preview planned under it.
		const answered =
			awaiting.seen ||
			(view.decision !== null &&
				!pending.dirty &&
				(view.approvable.code !== "not-accepted" || view.error !== null));
		if (!answered) return;
		setAwaiting(null);
		if (view.error) return;
		pending.reset();
		const { then } = awaiting;
		if (then.kind !== "approve") return;
		if (view.preview?.plan_digest !== awaiting.digest) {
			setChanged(true);
			return;
		}
		if (view.approvable.ok && (!awaitsKeepChoice(view) || then.keep))
			void approve(then.keep);
	}, [awaiting, running, view]);

	return {
		refusal,
		changed,
		sending,
		awaiting,
		busy: running || sending || awaiting !== null,
		submit,
		send,
		approve,
		move,
		refresh,
	};
}
