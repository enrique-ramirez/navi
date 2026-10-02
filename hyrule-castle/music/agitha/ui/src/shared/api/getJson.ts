export async function getJson<Body>(url: string): Promise<Body> {
	const response = await fetch(url);
	if (!response.ok) throw new Error(String(response.status));
	return response.json();
}
