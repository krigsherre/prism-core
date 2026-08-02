export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
      const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

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
