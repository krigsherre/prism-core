export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "/api/brain";

interface ApiOptions extends RequestInit {
  data?: any;
}

class ApiClient {
  private async request<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
    const { data, headers, ...customConfig } = options;

    let config: RequestInit = {
      ...customConfig,
      headers: { ...headers },
    };

    if (data instanceof FormData) {
      config.body = data;
    } else if (data) {
      config.headers = {
        "Content-Type": "application/json",
        ...config.headers,
      };
      config.body = JSON.stringify(data);
    }

    try {
      let finalUrl = endpoint;

      if (endpoint.startsWith('/api/v1/') || endpoint.startsWith('/api/gateway')) {
        // Next.js API routes (/api/v1/*) or gateway — use path as-is
        finalUrl = endpoint;
      } else if (endpoint.startsWith('/api/')) {
        // All other /api/* go to agentic-brain via the /api/brain rewrite
        finalUrl = `${API_BASE_URL}${endpoint.substring(4)}`;
      } else if (!endpoint.startsWith('http')) {
        finalUrl = `${API_BASE_URL}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
      }

      const response = await fetch(finalUrl, config);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || errorData.message || `API Error: ${response.status}`);
      }

      return response.json() as Promise<T>;
    } catch (error: any) {
      console.error(`[API Client Error] ${endpoint}:`, error.message);
      throw error;
    }
  }

  get<T>(endpoint: string, options?: Omit<ApiOptions, 'body' | 'data' | 'method'>) {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  }

  post<T>(endpoint: string, data?: any, options?: Omit<ApiOptions, 'body' | 'method' | 'data'>) {
    return this.request<T>(endpoint, { ...options, method: 'POST', data });
  }
}

export const api = new ApiClient();
