/** The first file a drop carries, from the file list or, where a browser leaves that empty, the items. */
export function droppedFile(data: DataTransfer): File | null | undefined {
	return (
		data.files?.[0] ??
		Array.from(data.items ?? [])
			.find((item) => item.kind === "file")
			?.getAsFile()
	);
}
