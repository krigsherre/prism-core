import { NextRequest, NextResponse } from "next/server";

export const dynamic = 'force-dynamic';
export const maxDuration = 300

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const tenantId = url.searchParams.get("tenant_id") || "default-tenant";

  const backendUrl = `http://agentic-brain:8001/api/documents/status/stream?tenant_id=${tenantId}`;

  try {
    const response = await fetch(backendUrl, {
      method: 'GET',
      headers: {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
      },
      cache: "no-store",
    });

    return new NextResponse(response.body, {
      status: response.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (error) {
    console.error("SSE Proxy Error:", error);
    return NextResponse.json({ error: "Failed to connect to stream" }, { status: 500 });
  }
}
