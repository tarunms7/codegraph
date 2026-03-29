export interface IUser {
    name: string;
    email: string;
}

export interface IAuthConfig {
    secret: string;
    expiresIn: number;
}

export type Role = 'admin' | 'user' | 'guest';

export enum Permission {
    READ = 'read',
    WRITE = 'write',
    ADMIN = 'admin',
}
