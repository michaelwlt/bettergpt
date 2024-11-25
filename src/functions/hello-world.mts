import { Config, Context } from '@netlify/functions';

export default async (req: Request, context: Context) => {
	return new Response('Hello, world!');
};

export const config: Config = {
	// this will ensure the function runs on the /hello path instead of /.netlify/functions/YOUR_SF_PREFIX_hello-world
	path: '/hello'
};
