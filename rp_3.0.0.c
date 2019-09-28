	/*
		Conventions:
		Comments are tabbed one extra level in.
		Debugging is commented at head-of-line, regardless of indentation.
	*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

	/*
		From the ruby code:
		require 'cgi'
		require 'json'
		require 'net/http'
		require 'uri'
		require 'sqlite3'
		require 'base64'
		require 'date'
	*/

	/*
		I stole this CGI code from
		https://www.eskimo.com/~scs/cclass/handouts/cgi.html
	*/
extern char *cgigetval(char *);
char *unescstring(char *, int, char *, int);
static int xctod(int);

char *unescstring(char *src, int srclen, char *dest, int destsize)
{
	char *endp = src + srclen;
	char *srcp;
	char *destp = dest;
	int nwrote = 0;

	for(srcp = src; srcp < endp; srcp++)
	{
		if(nwrote > destsize)
			return NULL;

		if(*srcp == '+')
			*destp++ = ' ';
		else if(*srcp == '%')
		{
			*destp++ = 16 * xctod(*(srcp+1)) + xctod(*(srcp+2));
			srcp += 2;
		}
		else
			*destp++ = *srcp;
		nwrote++;
		}

	*destp = '\0';

	return dest;
}

static int xctod(int c)
{
	if(isdigit(c))
		return c - '0';
	else if(isupper(c))
		return c - 'A' + 10;
	else if(islower(c))
		return c - 'a' + 10;
	else
		return 0;
}

char *cgigetval(char *fieldname)
{
	int fnamelen;
	char *p, *p2, *p3;
	int len1, len2;
	static char *querystring = NULL;
	if(querystring == NULL)
	{
		querystring = getenv("QUERY_STRING");
		if(querystring == NULL) return NULL;
	}

	if(fieldname == NULL)
		return NULL;

	fnamelen = strlen(fieldname);

	for(p = querystring; *p != '\0';)
	{
		p2 = strchr(p, '=');
		p3 = strchr(p, '&');
		if(p3 != NULL)
			len2 = p3 - p;
		else
			len2 = strlen(p);

		if(p2 == NULL || (p3 != NULL && p2 > p3))
		{
				/* no = present in this field */
			p3 += len2;
			continue;
		}
		len1 = p2 - p;

		if(len1 == fnamelen && strncmp(fieldname, p, len1) == 0)
		{
			/* found it */
			int retlen = len2 - len1 - 1;
			char *retbuf = malloc(retlen + 1);
			if(retbuf == NULL)
				return NULL;
			unescstring(p2 + 1, retlen, retbuf, retlen+1);
			return retbuf;
		}

		p += len2;
		if(*p == '&')
			p++;
	}

		/* never found it */
	return NULL;
}

int main(void)
{
		/*
			Apache seems to queue the response occasionally; timeouts still
			occur. I have to tear down that output channel so Apache releases
			the response as soon as possible, so this ends up being the real
			solution:

			Answer quickly and close stdout so Apache releases and Slack gets
			its timely response.
		*/

/*	printf("Content-type: text/plain\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"); */

	char *token;
	char *CGI_CONTENT_LENGTH = getenv("CONTENT_LENGTH");
	int content_length = 0;

	if (CGI_CONTENT_LENGTH != NULL)
		content_length = atoi(CGI_CONTENT_LENGTH);

	printf("Content-type: text/plain\r\nTransfer-Encoding: Chunked\r\nConnection: close\r\n\r\n");

/* char *CGI_USER_AGENT = getenv("HTTP_USER_AGENT");
	int ualen = 0;

	if (CGI_USER_AGENT != NULL)
	{
		ualen = strlen(CGI_USER_AGENT);
		fprintf(stderr,"%x\r\n",ualen);
		fprintf(stderr,"%s\n",CGI_USER_AGENT);
	}
*/

	if (content_length > 0)
	{
/*		int cllen = strlen(CGI_CONTENT_LENGTH);
		fprintf(stderr,"%x\r\n",cllen); */
		fprintf(stderr,"%d\n",content_length);
	}

	printf("0\r\n\r\n");
	fclose(stdout);

		/*
			ALL THE CODE FOR THE RP BOT GOES HERE.
		*/

		/* Database is? This is where I will likely change to a simpler
			configuration, probably a simple text file. */
/*	token = cgigetval("token");
	fprintf(stderr,"%s",token); */

		/* If you get to the end, exit fine. */
	return 0;
}
