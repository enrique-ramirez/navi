// The same drawing as public/favicon.svg, which Parasol.test.tsx compares shape by shape.
export function Parasol({
	title,
	size = 24,
}: {
	title?: string;
	size?: number;
}) {
	return (
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 32 32"
			width={size}
			height={size}
			fill="none"
			stroke="currentColor"
			strokeWidth={2}
			strokeLinecap="round"
			strokeLinejoin="round"
			role={title ? "img" : undefined}
			aria-label={title}
			aria-hidden={title ? undefined : true}
		>
			<path d="M3 15A13 12 0 0 1 29 15Q25.5 12.5 22.5 15Q19.5 12.5 16 15Q12.5 12.5 9.5 15Q6.5 12.5 3 15Z" />
			<path d="M16 3V15M9.5 4.6V15M22.5 4.6V15" />
			<path d="M16 15V26a3 3 0 0 0 6 0" />
		</svg>
	);
}
