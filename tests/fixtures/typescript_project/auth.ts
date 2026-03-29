import { IUser, IAuthConfig } from './types';

export class AuthService {
    private config: IAuthConfig;

    constructor(config: IAuthConfig) {
        this.config = config;
    }

    authenticate(token: string): IUser {
        const decoded = atob(token);
        const [name, email] = decoded.split(':');
        return { name, email };
    }

    authorize(user: IUser, permission: string): boolean {
        return user.email.endsWith('@admin.com') || permission === 'read';
    }
}

export function createToken(user: IUser): string {
    return btoa(`${user.name}:${user.email}`);
}
