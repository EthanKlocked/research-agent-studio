export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok)
      throw new Error(
        response.status === 404
          ? "실행 기록을 찾을 수 없습니다. 서버 재시작 시 기록이 사라질 수 있습니다."
          : response.status === 429
            ? "현재 실행이 많습니다. 잠시 후 다시 시도해 주세요."
            : "요청을 처리하지 못했습니다. 서버 상태와 입력을 확인해 주세요.",
      );
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("실행 기록"))
      throw error;
    if (
      error instanceof Error &&
      (error.message.startsWith("현재 실행") ||
        error.message.startsWith("요청을"))
    )
      throw error;
    throw new Error(
      "서버에 연결할 수 없습니다. 로컬 서버 실행 상태를 확인해 주세요.",
    );
  } finally {
    clearTimeout(timer);
  }
}
