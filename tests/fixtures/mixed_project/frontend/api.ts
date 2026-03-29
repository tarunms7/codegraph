export interface ApiResponse {
    data: any;
    status: number;
}

export async function fetchItems(): Promise<ApiResponse> {
    const response = await fetch('/api/items');
    const data = await response.json();
    return { data, status: response.status };
}

export class ApiClient {
    private baseUrl: string;

    constructor(baseUrl: string = '') {
        this.baseUrl = baseUrl;
    }

    async get(url: string): Promise<ApiResponse> {
        const response = await fetch(`${this.baseUrl}${url}`);
        const data = await response.json();
        return { data, status: response.status };
    }
}
