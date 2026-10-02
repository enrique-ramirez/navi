import type { UseQueryResult } from "@tanstack/react-query";

import { formatLength } from "@/domain/album/format";
import type { LibraryOrder, OrderFlag } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./TrackOrder.module.css";

/** Why the order was not checked, with Check again where asking again may help. Nothing while it is pending or flags nothing. */
export function OrderNote({ order }: { order: UseQueryResult<LibraryOrder> }) {
	const { t } = useTranslate();
	const data = order.data;
	const sentence = order.isError
		? t("order.requestFailed")
		: data && !data.checked
			? data.reason
			: null;
	if (sentence === null) return null;
	const retry =
		order.isError || (data !== undefined && !data.checked && data.retry);
	return (
		<p className={styles.note}>
			<span>{sentence}</span>
			{retry && (
				<button type="button" onClick={() => void order.refetch()}>
					{t("order.checkAgain")}
				</button>
			)}
		</p>
	);
}

/** What the order check and the draft say on one track's row: the flags it is in, and the swap it is part of. */
export function RowOrder({
	path,
	flags,
	swaps,
	labelOf,
	readOnly,
	onSwap,
}: {
	path: string;
	flags: OrderFlag[];
	swaps: [string, string][];
	labelOf: (path: string) => string;
	readOnly: boolean;
	onSwap: (pair: [string, string]) => void;
}) {
	const { t } = useTranslate();
	const mine = flags.filter((flag) => flag.a === path || flag.b === path);
	const swap = swaps.find((pair) => pair.includes(path));
	const other = swap?.find((each) => each !== path);
	if (mine.length === 0 && other === undefined) return null;
	return (
		<span className={styles.row}>
			{other !== undefined && (
				<span className={styles.mark}>
					{t("order.mark", { other: labelOf(other) })}
				</span>
			)}
			{mine.map((flag) => {
				const a = labelOf(flag.a);
				const b = labelOf(flag.b);
				return (
					<span key={`${flag.a}\n${flag.b}`} className={styles.flag}>
						<span>
							{t("order.flag", {
								a,
								b,
								aRuns: formatLength(flag.a_runs),
								aWants: formatLength(flag.a_wants),
								bRuns: formatLength(flag.b_runs),
								bWants: formatLength(flag.b_wants),
							})}
						</span>
						<button
							type="button"
							disabled={readOnly}
							onClick={() => onSwap([flag.a, flag.b])}
						>
							{t("order.swapPair", { a, b })}
						</button>
					</span>
				);
			})}
		</span>
	);
}
